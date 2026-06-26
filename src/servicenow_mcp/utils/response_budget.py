"""Bound a tool result's serialized size so the MCP client never SILENTLY
truncates it to an opaque scratchpad file — which is exactly what makes an
agent lose its place.

The client (Claude Code) caps a single tool result at ~MAX_MCP_OUTPUT_TOKENS
(default 25000). When the server returns more, the client abridges to a file on
the user's disk and the agent must guess where to resume.

Design — accuracy and not-getting-lost over byte count, and NEVER make it worse:

  1. Only RECORD-BACKED strings are abridged — a value is stubbed only when its
     immediate container carries a `sys_id`, so every stub can hand back a
     precise, correct re-fetch instruction. Computed values (a diff, a rendered
     payload) have no sys_id and are LEFT WHOLE: the client's scratchpad copy of
     them is recoverable, a stub of them would not be.
  2. Identity / safety / navigation keys are never abridged at any depth.
  3. The budget is measured in UTF-8 BYTES (CJK text is ~3 bytes/char), because
     that is what the client ceiling actually counts.
  4. Largest-first and minimal: stub as few fields as needed to fit; if records
     overflow by COUNT rather than size, drop trailing rows with a paging hint.
  5. Honest: if even that cannot fit (e.g. one huge protected field), return
     best-effort and say so — never claim a fit that did not happen.

Pure functions, no network, no mutation — fully unit-testable.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.utils import json_fast

# Client single-result ceiling proxy, in UTF-8 BYTES. Claude Code defaults to
# 25000 output tokens; we stay conservatively under the byte-equivalent so the
# JSON envelope + our stubs never tip the client into its own truncation.
# Override per-deployment to match a tuned MAX_MCP_OUTPUT_TOKENS.
ENV_BUDGET = "SERVICENOW_RESPONSE_BUDGET_CHARS"
DEFAULT_BUDGET_BYTES = 75_000
# Back-compat alias (the env var name and this constant predate the bytes rename).
DEFAULT_BUDGET_CHARS = DEFAULT_BUDGET_BYTES

# Only stub genuinely large bodies. Small per-row fields are handled by row
# truncation instead, so they never get a weak, table-less re-fetch hint.
MIN_STUB_FIELD_BYTES = 2_000

# Characters of the original value kept inline so the agent can still tell what
# the field holds without a follow-up call.
PREVIEW_CHARS = 240

# Keys whose values are identity / safety / navigation / computed-output signals.
# Never abridged, even when long, at any depth: losing them is how an agent gets
# lost or misjudges a write, and computed values cannot be re-fetched.
PROTECTED_KEYS = frozenset(
    {
        # identity / navigation
        "sys_id",
        "table",
        "name",
        "id",
        "success",
        "status",
        "operation",
        "target",
        "scope",
        "instance",
        "instance_url",
        "instance_name",
        "target_instance",
        "origin_instance",
        # safety / risk signals
        "error",
        "message",
        "hint",
        "risk",
        "level",
        "factors",
        "attribution",
        "warning",
        "warnings",
        "conflict_warning",
        "safety_notice",
        "note",
        "remote_updated_by",
        "remote_updated_on",
        "update_set",
        "update_sets",
        "current_update_set",
        "update_set_context",
        "held_by",
        # computed, non-record-backed outputs (cannot be re-fetched by sys_id)
        "diff",
        "diffs",
        "query_echo",
        "payload",
        "xml",
        # our own stub internals
        "_fetch",
        "_sha256",
        "_full_length",
        "_abridged",
        "_abridged_fields",
        "_abridged_note",
        "_truncated_items",
    }
)

# tool_name → ServiceNow table, for tools whose result does not carry `table`
# inline but whose code-bearing table is fixed.
_TABLE_BY_TOOL = {
    "get_widget_bundle": "sp_widget",
}

_PORTAL_TABLE_PREFIX = "sp_"

# Bytes reserved for the top-level abridged marker appended after row truncation.
_MARKER_RESERVE = 400


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #


def get_response_budget() -> int:
    """Soft UTF-8 byte budget for a single serialized tool result."""
    raw = os.getenv(ENV_BUDGET)
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_BUDGET_BYTES


def byte_len(obj: Any) -> int:
    """UTF-8 byte length of *obj* serialized as compact JSON."""
    return len(json_fast.dumps(obj).encode("utf-8"))


def _str_bytes(value: str) -> int:
    return len(value.encode("utf-8"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Stubs and fetch hints
# --------------------------------------------------------------------------- #


def _build_fetch_hint(key: Optional[str], sys_id: str, table: Optional[str], tool_name: str) -> str:
    """A correct, copy-pasteable instruction for fetching the abridged field alone.

    Only ever called for record-backed values (sys_id present), so the hint is
    always actionable.
    """
    table = table or _TABLE_BY_TOOL.get(tool_name)
    field = f"['{key}']" if key else "[...]"

    if table and table.startswith(_PORTAL_TABLE_PREFIX):
        return (
            f"Field '{key}' abridged to fit the response budget. Fetch it ALONE in CHUNKS: "
            f"get_portal_component_code(table='{table}', sys_id='{sys_id}', fields={field}, "
            f"fetch_complete=false, script_offset=0), then follow _{key}_next_offset while "
            f"_{key}_has_more is set."
        )
    if table:
        return (
            f"Field '{key}' abridged to fit the response budget. Fetch it ALONE: "
            f"sn_query(table='{table}', query='sys_id={sys_id}', fields='{key or ''}'). If that "
            f"single field still overflows, download it to disk via download_server_sources / "
            f"download_portal_sources instead."
        )
    return (
        f"Field '{key}' abridged to fit the response budget. Re-run {tool_name} scoped to this "
        f"record (sys_id={sys_id}) to get '{key}' in full."
    )


def _stub(
    key: Optional[str], value: str, sys_id: str, table: Optional[str], tool_name: str
) -> Dict[str, Any]:
    return {
        "_abridged": True,
        "_full_length": len(value),
        "_sha256": _sha256(value),
        "_preview": value[:PREVIEW_CHARS],
        "_fetch": _build_fetch_hint(key, sys_id, table, tool_name),
    }


# --------------------------------------------------------------------------- #
# Field stubbing (record-backed large strings)
# --------------------------------------------------------------------------- #


def _container_sys_id(obj: Dict[str, Any]) -> str:
    # ServiceNow sys_ids are always 32-char hex strings; anything else is not a
    # record handle we can build a re-fetch hint from.
    sid = obj.get("sys_id")
    return sid.strip() if isinstance(sid, str) else ""


def _collect_eligible(obj: Any) -> List[int]:
    """Byte lengths of every stub-eligible string leaf.

    Eligible = a string whose immediate container dict has a sys_id, whose key is
    not protected, and whose UTF-8 size is at least MIN_STUB_FIELD_BYTES.
    Protected-key subtrees are skipped entirely.
    """
    out: List[int] = []
    if isinstance(obj, dict):
        sys_id = _container_sys_id(obj)
        for key, value in obj.items():
            if key in PROTECTED_KEYS:
                continue
            if isinstance(value, (dict, list)):
                out.extend(_collect_eligible(value))
            elif isinstance(value, str) and sys_id and _str_bytes(value) >= MIN_STUB_FIELD_BYTES:
                out.append(_str_bytes(value))
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                out.extend(_collect_eligible(item))
    return out


def _abridge_strings(
    obj: Any, *, tool_name: str, threshold: int, stubbed: List[str], path: str = ""
) -> Any:
    """Return a NEW structure with record-backed string leaves >= *threshold*
    bytes replaced by stubs. Protected-key subtrees are copied whole."""
    if isinstance(obj, dict):
        sys_id = _container_sys_id(obj)
        table = obj.get("table") if isinstance(obj.get("table"), str) else None
        out: Dict[str, Any] = {}
        for key, value in obj.items():
            child = f"{path}.{key}" if path else key
            if key in PROTECTED_KEYS:
                out[key] = value
            elif isinstance(value, (dict, list)):
                out[key] = _abridge_strings(
                    value, tool_name=tool_name, threshold=threshold, stubbed=stubbed, path=child
                )
            elif isinstance(value, str) and sys_id and _str_bytes(value) >= threshold:
                out[key] = _stub(key, value, sys_id, table, tool_name)
                stubbed.append(child)
            else:
                out[key] = value
        return out
    if isinstance(obj, list):
        return [
            _abridge_strings(
                item, tool_name=tool_name, threshold=threshold, stubbed=stubbed, path=f"{path}[{i}]"
            )
            for i, item in enumerate(obj)
        ]
    return obj


def _with_marker(obj: Any, stubbed: List[str]) -> Any:
    """Attach the top-level abridged marker (dict results only) for measurement."""
    if isinstance(obj, dict) and stubbed:
        return {**obj, "_abridged_fields": stubbed, "_abridged_note": _ABRIDGED_NOTE}
    return obj


_ABRIDGED_NOTE = (
    "Large values were abridged to fit the response budget; each stub carries _full_length, "
    "_sha256, _preview, and a _fetch hint. This is NOT the complete content — fetch any field "
    "you need in full via its _fetch instruction."
)


def _fit_by_stubbing(
    result: Any, *, tool_name: str, eligible: List[int], budget: int
) -> Tuple[Any, List[str]]:
    """Stub the fewest (largest-first) record-backed fields needed to fit budget.

    Binary-searches the byte threshold; if even stubbing every eligible field
    cannot fit, returns the all-stubbed best effort.
    """
    ordered = sorted(eligible, reverse=True)
    found: Optional[Tuple[Any, List[str]]] = None
    lo, hi = 1, len(ordered)
    while lo <= hi:
        mid = (lo + hi) // 2
        threshold = ordered[mid - 1]
        stubbed: List[str] = []
        cand = _abridge_strings(result, tool_name=tool_name, threshold=threshold, stubbed=stubbed)
        if byte_len(_with_marker(cand, stubbed)) <= budget:
            found = (cand, stubbed)
            hi = mid - 1
        else:
            lo = mid + 1
    if found is not None:
        return found
    stubbed = []
    cand = _abridge_strings(result, tool_name=tool_name, threshold=ordered[-1], stubbed=stubbed)
    return cand, stubbed


# --------------------------------------------------------------------------- #
# Row truncation (lists that overflow by element COUNT)
# --------------------------------------------------------------------------- #


def _largest_list(obj: Any, path: Tuple[Any, ...] = ()) -> Optional[Tuple[Tuple[Any, ...], int]]:
    """Locate the (path, byte_len) of the largest non-protected list, or None."""
    best: Optional[Tuple[Tuple[Any, ...], int]] = None
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in PROTECTED_KEYS:
                continue
            best = _max_candidate(best, _largest_list(value, path + (key,)))
            if isinstance(value, list) and len(value) > 1:
                best = _max_candidate(best, (path + (key,), byte_len(value)))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            best = _max_candidate(best, _largest_list(item, path + (index,)))
            if isinstance(item, list) and len(item) > 1:
                best = _max_candidate(best, (path + (index,), byte_len(item)))
    return best


def _max_candidate(
    a: Optional[Tuple[Tuple[Any, ...], int]], b: Optional[Tuple[Tuple[Any, ...], int]]
) -> Optional[Tuple[Tuple[Any, ...], int]]:
    if a is None:
        return b
    if b is None:
        return a
    return a if a[1] >= b[1] else b


def _get_at(obj: Any, path: Tuple[Any, ...]) -> Any:
    for step in path:
        obj = obj[step]
    return obj


def _set_at(obj: Any, path: Tuple[Any, ...], value: Any) -> Any:
    """Immutably return a copy of *obj* with the node at *path* replaced."""
    if not path:
        return value
    step, rest = path[0], path[1:]
    if isinstance(obj, dict):
        return {**obj, step: _set_at(obj[step], rest, value)}
    if isinstance(obj, list):
        return [_set_at(item, rest, value) if i == step else item for i, item in enumerate(obj)]
    return value


def _fit_by_row_truncation(bounded: Any, *, budget: int, reserve: int) -> Tuple[Any, int]:
    """Drop trailing elements of the largest list until the result fits.

    Returns (new_result, dropped_count). dropped_count is 0 when no list could
    help (best effort).
    """
    located = _largest_list(bounded)
    if located is None:
        return bounded, 0
    path, _ = located
    rows = _get_at(bounded, path)
    if not isinstance(rows, list) or len(rows) <= 1:
        return bounded, 0

    # Largest keep-count whose truncated result still fits, reserving room for
    # the top-level abridged marker that enforce_response_budget appends after
    # (which carries the variable-size _abridged_fields list — sized by caller).
    target = max(0, budget - reserve)
    lo, hi, best_keep = 0, len(rows) - 1, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        dropped = len(rows) - mid
        kept = rows[:mid] + [_row_marker(dropped)]
        if byte_len(_set_at(bounded, path, kept)) <= target:
            best_keep = mid
            lo = mid + 1
        else:
            hi = mid - 1

    dropped = len(rows) - best_keep
    kept = rows[:best_keep] + [_row_marker(dropped)]
    return _set_at(bounded, path, kept), dropped


def _row_marker(dropped: int) -> Dict[str, Any]:
    return {
        "_truncated_items": dropped,
        "_fetch": (
            f"{dropped} more items omitted to fit the response budget. Narrow the query or "
            "re-run the producing tool with a smaller scope to retrieve them."
        ),
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def enforce_response_budget(
    result: Any,
    *,
    tool_name: str,
    budget: Optional[int] = None,
) -> Tuple[Any, bool]:
    """Abridge oversized values so the serialized result fits *budget* bytes.

    Returns (possibly-new result, was_abridged). Small results are returned
    unchanged. Never mutates the input and never destroys non-recoverable data.
    """
    if not isinstance(result, (dict, list)):
        return result, False

    budget = budget if budget is not None else get_response_budget()
    if byte_len(result) <= budget:
        return result, False

    stubbed: List[str] = []
    bounded: Any = result

    eligible = _collect_eligible(result)
    if eligible:
        bounded, stubbed = _fit_by_stubbing(
            result, tool_name=tool_name, eligible=eligible, budget=budget
        )

    dropped = 0
    if byte_len(_with_marker(bounded, stubbed)) > budget:
        # Reserve room for the marker enforce appends, whose _abridged_fields list
        # grows with the stub count — a fixed reserve would undercount it.
        reserve = _MARKER_RESERVE + (byte_len(stubbed) if stubbed else 0)
        bounded, dropped = _fit_by_row_truncation(bounded, budget=budget, reserve=reserve)

    if not stubbed and dropped == 0:
        # Oversized but nothing safely abridgeable (e.g. one huge protected
        # field). Leave it whole — the client's scratchpad copy is recoverable.
        return result, False

    if isinstance(bounded, dict):
        marker: Dict[str, Any] = {"_abridged_note": _ABRIDGED_NOTE}
        if stubbed:
            marker["_abridged_fields"] = stubbed
        if dropped:
            marker["_truncated_items"] = dropped
        still_over = byte_len({**bounded, **marker}) > budget
        if still_over:
            marker["_abridged_note"] = (
                _ABRIDGED_NOTE + " NOTE: still over budget after best-effort abridging; "
                "the client may store the remainder in an overflow file."
            )
        bounded = {**bounded, **marker}

    return bounded, True
