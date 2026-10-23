"""ServiceNow Batch API fusion (documented ``/api/now/v1/batch``).

Many-small-queries hot paths (verdict scans, watermark checks) pay ONE HTTP
round trip instead of N: the sub-requests ride a single POST and the server
fans them out internally. On a 150-300ms RTT link this turns a 20-query scan
from seconds into one round trip.

Availability is probed implicitly and cached per instance for the process
lifetime: a 404/405/400 on the batch endpoint marks the instance unsupported
and every caller falls back to its per-request path — same results, old
latency, no half-working states. Transient failures (network, 5xx) are NOT
cached so one hiccup doesn't disable the fast path forever.

Documented API — safe for basic/OAuth/API-key auth (no undocumented-endpoint
exception needed; see CLAUDE.md auth separation).
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils import json_fast
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.http_result import json_object

logger = logging.getLogger(__name__)

_BATCH_PATH = "/api/now/v1/batch"
# instance_url -> False when the endpoint is structurally absent/blocked.
# Only structural rejections are cached; transient errors keep retrying.
_batch_unsupported: Dict[str, bool] = {}

_STRUCTURAL_REJECTIONS = {400, 404, 405, 501}

# What the server appends to the sub-request it was streaming when a batch POST
# hit its output cap. Measured live: five 50-record source chunks (~7.9MB of
# JSON, 10.5MB as base64) — the fifth came back 500 with this tail, and alone it
# was a clean 200.
_OUTPUT_CAP_MARKER = "Max output size reached"
# POSTs per batch_get. Each re-batch carries only the cut ids, so this bounds a
# scan of roughly 4x the cap before the remainder falls back per id.
_MAX_OUTPUT_ROUNDS = 4


def reset_batch_support_cache() -> None:
    """Test hook: forget per-instance availability verdicts."""
    _batch_unsupported.clear()


def table_query_url(
    table: str,
    query: str,
    fields: str,
    *,
    limit: int,
    display_value: bool = False,
) -> str:
    """Relative Table-API GET url for one arbitrary query — a batch sub-request.

    ``sync_tools._table_chunk_url`` builds the same shape but only ever for a
    ``sys_idIN`` chunk with display values off. Fusing reads that need labels
    (the flow-structure fallback resolves reference fields to names) needs the
    general form, so it lives here beside :func:`batch_get` rather than being
    copied per call site.

    Ordering is deliberately not a parameter: an ORDERBY clause belongs inside
    ``query`` like any other encoded-query term. There is no `sysparm_orderby`
    on this API — passing one is accepted and ignored, which is how ordered
    reads silently came back unordered before v1.22.26.
    """
    return f"/api/now/table/{table}?" + urlencode(
        {
            "sysparm_query": query,
            "sysparm_fields": fields,
            "sysparm_limit": str(limit),
            "sysparm_display_value": "true" if display_value else "false",
            "sysparm_exclude_reference_link": "true",
        }
    )


def batch_rows(served: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """The ``result`` rows of one serviced sub-request, or None to fall back.

    None means "this sub-request did not come back usable" — absent id, non-200,
    or a body that is not the expected object. Callers must then issue the plain
    GET they would have made anyway; a batch that partly fails must never look
    like a batch that returned nothing.
    """
    if not isinstance(served, dict) or served.get("status_code") != 200:
        return None
    body = served.get("body")
    if not isinstance(body, dict):
        return None
    rows = body.get("result")
    return rows if isinstance(rows, list) else None


def batch_get(
    config: ServerConfig,
    auth_manager: AuthManager,
    requests_by_id: List[Tuple[str, str]],
    timeout: int = 60,
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Execute GET sub-requests in ONE round trip.

    ``requests_by_id``: (id, relative_url) pairs — relative_url like
    ``/api/now/table/incident?sysparm_query=...``.

    Returns ``{id: {"status_code": int, "body": parsed-JSON-or-None}}`` for every
    SERVICED sub-request. Sub-response headers are deliberately NOT returned: no
    caller consumes them (pagination reads ``X-Total-Count`` off its own direct
    GET, not off a batch sub-response), so echoing a header dict per sub-request
    was pure context weight. Unparsable bodies are still logged at DEBUG.
    Ids the server did not service are simply absent — the caller falls back
    per-id. Returns ``None`` when the Batch API itself is unavailable (caller
    must fall back entirely).
    """
    if not requests_by_id:
        return {}
    instance = config.instance_url.rstrip("/")
    if _batch_unsupported.get(instance):
        return None

    out: Dict[str, Dict[str, Any]] = {}
    pending = list(requests_by_id)
    for round_no in range(_MAX_OUTPUT_ROUNDS):
        posted = _post_batch(auth_manager, instance, pending, timeout)
        if posted is None:
            # The first POST failing means no batch at all; a later one only
            # loses the re-batch — what already came back stands, and the cut
            # ids stay in `out` as failures so callers fall back per id.
            return None if round_no == 0 else out
        served, cut = posted
        out.update(served)
        if not cut or len(cut) == len(pending):
            # Done, or no progress: a sub-request over the cap on its own will
            # not fit in any batch — it is left to the caller's direct GET.
            break
        logger.info(
            "batch_get: output cap reached; re-batching %d of %d sub-request(s)",
            len(cut),
            len(pending),
        )
        pending = [spec for spec in pending if spec[0] in cut]
    return out


def _post_batch(
    auth_manager: AuthManager,
    instance: str,
    requests_by_id: List[Tuple[str, str]],
    timeout: int,
) -> Optional[Tuple[Dict[str, Dict[str, Any]], Set[str]]]:
    """One batch POST. Returns (serviced, cut) or None when the API is unusable.

    ``cut`` holds the ids the server stopped on because the transaction hit its
    output cap ("Max output size reached for current BatchRest transaction"),
    and every id it lists as unserviced. Each sub-request is fine on its own; the
    cap is per POST (~10MB of base64, so ~7.5MB of JSON), so they belong in
    the next POST, not in a per-id fallback.
    """
    payload = {
        "batch_request_id": "1",
        "rest_requests": [
            {
                "id": str(rid),
                "url": rel_url,
                "method": "GET",
                "headers": [{"name": "Accept", "value": "application/json"}],
            }
            for rid, rel_url in requests_by_id
        ],
    }
    try:
        response = auth_manager.make_request(
            "POST", f"{instance}{_BATCH_PATH}", json=payload, timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001 — transient; caller falls back, no caching
        logger.warning("batch_get: request failed (falling back): %s", exc)
        return None

    status = getattr(response, "status_code", None)
    if status in _STRUCTURAL_REJECTIONS:
        logger.info("batch_get: %s on %s — Batch API unsupported, cached", status, instance)
        _batch_unsupported[instance] = True
        return None
    if status != 200:
        logger.warning("batch_get: HTTP %s (falling back, not cached)", status)
        return None

    try:
        envelope = json_object(response, "batch API")
    except ValueError as exc:
        logger.warning("batch_get: unparsable response (falling back): %s", exc)
        return None
    serviced = envelope.get("serviced_requests") or []
    # Ids the server never got to. Measured live: when the cap is hit, the
    # sub-request being streamed is cut — sometimes with the error appended,
    # sometimes just stopped — and everything after it lands here.
    unserviced = {str(rid) for rid in envelope.get("unserviced_requests") or []}

    out: Dict[str, Dict[str, Any]] = {}
    cut: Set[str] = set(unserviced)
    for item in serviced:
        rid = str(item.get("id") or "")
        if not rid:
            continue
        body: Any = None
        raw = item.get("body")
        if isinstance(raw, str) and raw:
            try:
                body = json_fast.loads(base64.b64decode(raw))
            except (ValueError, TypeError) as exc:
                try:
                    decoded = base64.b64decode(raw).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001 — diagnostics must never raise
                    decoded = ""
                status_code = int(item.get("status_code") or 0)
                if _OUTPUT_CAP_MARKER in decoded[-600:] or (status_code == 500 and unserviced):
                    # Not a bad body: the rows were streamed until the cap and
                    # then stopped. Re-batched by the caller.
                    cut.add(rid)
                else:
                    logger.warning("batch_get: sub-request %s body unparsable: %s", rid, exc)
                    # The raw body (usually an HTML error page) at DEBUG, so the
                    # cause (login bounce, 5xx, WAF block) is identifiable from
                    # the log alone, without leaking it at WARN.
                    logger.debug("batch_get: sub-request %s raw body[:200]=%r", rid, decoded[:200])
        out[rid] = {
            "status_code": int(item.get("status_code") or 0),
            "body": body,
        }
    if cut:
        # Whatever the server dropped after the cut belongs to the next POST too.
        cut |= {rid for rid, _url in requests_by_id if rid not in out}
    return out, cut
