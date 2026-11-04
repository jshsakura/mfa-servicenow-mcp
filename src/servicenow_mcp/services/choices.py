"""Resolve a value a caller wants to WRITE against the instance's own choice list.

ServiceNow does not refuse a value that is not one of a choice field's options:
`item_option_new.type = "string"` and `kb_knowledge.workflow_state = "live"` are
both stored and answered 200, and the record is left in a state the platform's
own forms and workflows do not recognise. So a write to a choice field resolves
the value first — a code, or its English label — against `sys_choice` on the
live instance, never against a list pinned in this repo (instances add their
own options).

A choice list that cannot be read, or comes back empty, is NOT a pass: the
write is refused and says why.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value


def _normalise(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _order(code: str) -> Tuple[bool, int, str]:
    try:
        return (False, int(code), code)
    except ValueError:
        return (True, 0, code)


_MAX_PARENT_HOPS = 4
_NUMBER_PREFIX = re.compile(r"^\s*-?\d+\s*-\s*")


def _read(config: ServerConfig, auth_manager: AuthManager, **kw: Any) -> list:
    rows, _ = sn_query_page(
        config, auth_manager, offset=0, no_count=True, fail_silently=False, **kw
    )
    return rows


def _choice_rows(config: ServerConfig, auth_manager: AuthManager, table: str, element: str) -> list:
    """Choices for ``table.element``, inherited from the nearest parent that has them.

    A child table often declares none of its own: incident.priority's options
    live on `task`. Stopping at the child would refuse every valid value.
    """
    current: Optional[str] = table
    seen = set()
    for _hop in range(_MAX_PARENT_HOPS + 1):
        if not current or current in seen:
            break
        seen.add(current)
        rows = _read(
            config,
            auth_manager,
            table="sys_choice",
            query=(
                f"name={safe_value(current).value}^element={safe_value(element).value}"
                "^inactive=false^language=en"
            ),
            fields="value,label",
            limit=200,
        )
        if rows:
            return rows
        parent = _read(
            config,
            auth_manager,
            table="sys_db_object",
            query=f"name={safe_value(current).value}",
            fields="super_class.name",
            limit=1,
        )
        current = str(parent[0].get("super_class.name") or "") if parent else None
    return []


def resolve_payload_choices(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    data: Dict[str, Any],
    elements: Tuple[str, ...],
) -> Optional[Dict[str, Any]]:
    """Resolve each present choice field of ``data`` in place; a refusal stops the write."""
    for element in elements:
        value = data.get(element)
        if value is None or value == "":
            continue
        resolved, refusal = resolve_choice(
            config, auth_manager, table=table, element=element, requested=str(value)
        )
        if refusal is not None:
            return refusal
        data[element] = resolved
    return None


def resolve_choice(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    element: str,
    requested: str,
    unknown_error: str = "UNKNOWN_CHOICE",
    unverified_error: str = "CHOICE_UNVERIFIED",
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Return ``(value, None)`` for a known value or label, else ``(None, refusal)``."""
    column = f"{table}.{element}"
    try:
        rows = _choice_rows(config, auth_manager, table, element)
    except Exception as e:
        return None, {
            "success": False,
            "error": unverified_error,
            "message": f"Could not read the choices for {column} (sys_choice): {e}. "
            "Nothing was written.",
        }
    choices: Dict[str, str] = {}
    for row in rows:
        value = str(row.get("value") or "").strip()
        if value:
            choices.setdefault(value, str(row.get("label") or ""))
    if not choices:
        return None, {
            "success": False,
            "error": unverified_error,
            "message": f"The choice list for {column} came back empty, so {requested!r} "
            "cannot be checked. Nothing was written.",
        }
    wanted = str(requested).strip()
    if wanted in choices:
        return wanted, None
    matches = [v for v, label in choices.items() if _normalise(label) == _normalise(wanted)]
    if not matches:
        # Numbered labels ("1 - High") are asked for by their word ("High").
        matches = [
            v
            for v, label in choices.items()
            if _normalise(_NUMBER_PREFIX.sub("", label)) == _normalise(wanted)
        ]
    if len(matches) == 1:
        return matches[0], None
    listing = ", ".join(f"{v}={choices[v]}" for v in sorted(choices, key=_order))
    return None, {
        "success": False,
        "error": unknown_error,
        "message": f"{requested!r} is not a value of {column} on this instance. "
        f"It takes a value or its label: {listing}. Nothing was written.",
    }
