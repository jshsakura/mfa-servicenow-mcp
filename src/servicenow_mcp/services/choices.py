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
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value
from servicenow_mcp.utils.query_fields import table_ancestry


def _normalise(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _order(code: str) -> Tuple[bool, int, str]:
    try:
        return (False, int(code), code)
    except ValueError:
        return (True, 0, code)


_NUMBER_PREFIX = re.compile(r"^\s*-?\d+\s*-\s*")


def _choice_rows(
    config: ServerConfig, auth_manager: AuthManager, table: str, element: str
) -> List[Dict[str, Any]]:
    """Choices for ``table.element``, from the nearest table in its ancestry that has any.

    A child table often declares none of its own (incident.priority's options can
    live on `task`); stopping at the child would refuse every valid value. The
    ancestry is walked by sys_id (``table_ancestry``) and read in one query; the
    nearest table with rows wins, as it does on the platform.
    """
    ancestry = table_ancestry(config, auth_manager, table)
    if not ancestry:
        raise RuntimeError(f"could not read the table hierarchy of {table}")
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_choice",
        query=(
            "nameIN"
            + ",".join(safe_value(t).value for t in ancestry)
            + f"^element={safe_value(element).value}^inactive=false^language=en"
        ),
        fields="name,value,label,dependent_value",
        limit=500,
        offset=0,
        no_count=True,
        fail_silently=False,
    )
    for name in ancestry:
        own = [r for r in rows if str(r.get("name") or "") == name]
        if own:
            return own
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
    depends_on: Optional[str] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Return ``(value, None)`` for a known value or label, else ``(None, refusal)``.

    ``depends_on`` narrows a dependent choice to the options its parent value
    allows (alm_asset.substatus under install_status): "Disposed" is a substatus
    of Retired only, and the platform stores it under In stock without a word.
    """
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
    if depends_on is not None:
        rows = [r for r in rows if str(r.get("dependent_value") or "") == str(depends_on)]
        column = f"{column} (for {depends_on})"
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
