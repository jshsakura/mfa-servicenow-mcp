"""Offline-first analysis: answer dependency/impact questions from the on-disk
graph files (no ServiceNow API).

After download_app_sources + audit_local_sources, the relationship graphs sit on
disk (_cross_references.json, _page_graph.json, _source_index.json). This tool
reads them back to answer the questions analysts actually ask — "what does X
use?", "what uses X?", "what's on page Y?", "what breaks if I change X?" —
instantly, token-cheap, and with ZERO API calls. The audit already tells the LLM
"the data is on disk"; this is the tool that consumes it.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

_CROSS_REFS_FILE = "_cross_references.json"
_PAGE_GRAPH_FILE = "_page_graph.json"

# Actions answered purely from local graph files.
_VALID_ACTIONS = ("uses", "used_by", "page", "impact")

_NEXT_STEP_NO_ANALYSIS = (
    "No local analysis found. Run download_app_sources(scope=...) then "
    "audit_local_sources(source_root=...) first — this tool then answers "
    "offline with zero API calls."
)


class QueryLocalGraphParams(BaseModel):
    source_root: str = Field(
        ..., description="Scope root holding the audit graph files (_cross_references.json)."
    )
    action: str = Field(..., description="uses | used_by | page | impact (all answered offline).")
    name: str = Field(..., description="Source/page name to look up (widget, SI, provider, page).")


def _read_json(path: Path) -> Optional[Any]:
    """Load a JSON file, or None if absent/unreadable. Never raises."""
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("local graph read failed for %s: %s", path, exc)
        return None


def _missing_analysis(root: Path) -> Dict[str, Any]:
    return {
        "success": False,
        "offline": True,
        "api_calls": 0,
        "error": f"No local analysis found at {root}.",
        "next_step": _NEXT_STEP_NO_ANALYSIS,
    }


def _answer_uses(cross_refs: Dict[str, Any], name: str) -> Dict[str, Any]:
    outgoing = (cross_refs.get("outgoing") or {}).get(name)
    found = outgoing is not None
    return {
        "result": outgoing or {},
        "found": found,
        "summary": (
            f"{name} references " + ", ".join(f"{len(v)} {k}" for k, v in (outgoing or {}).items())
            if found
            else f"{name} is not in the local graph (downloaded? references nothing?)."
        ),
    }


def _answer_used_by(cross_refs: Dict[str, Any], name: str) -> Dict[str, Any]:
    incoming = (cross_refs.get("incoming") or {}).get(name)
    found = incoming is not None
    callers = incoming or []
    return {
        "result": callers,
        "found": found,
        "summary": (
            f"{len(callers)} source(s) reference {name}."
            if found
            else f"Nothing references {name} in the local graph (possible orphan)."
        ),
    }


def _answer_impact(cross_refs: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Who breaks if `name` changes: direct callers + any source using `name`'s
    table. 1-hop, offline — the honest blast radius from local data."""
    incoming_map = cross_refs.get("incoming") or {}
    direct = incoming_map.get(name) or []
    via_table = incoming_map.get(f"table:{name}") or []
    impacted = direct + [c for c in via_table if c not in direct]
    return {
        "result": impacted,
        "found": bool(impacted),
        "summary": f"{len(impacted)} source(s) depend on {name} (1-hop, offline).",
    }


def _answer_page(root: Path, name: str) -> Dict[str, Any]:
    page_graph = _read_json(root / _PAGE_GRAPH_FILE) or {}
    widgets = page_graph.get(name)
    found = widgets is not None
    return {
        "result": widgets or [],
        "found": found,
        "summary": (
            f"Page {name} hosts {len(widgets or [])} widget(s)."
            if found
            else f"Page {name} not found in the local page graph."
        ),
    }


@register_tool(
    "query_local_graph",
    params=QueryLocalGraphParams,
    description="Offline dependency/impact answers from audit graph files (0 API). uses|used_by|page|impact.",
    serialization="raw_dict",
    return_type=dict,
)
def query_local_graph(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: QueryLocalGraphParams,
) -> Dict[str, Any]:
    """Answer a dependency/impact/placement question from local graph files."""
    action = params.action.strip().lower()
    if action not in _VALID_ACTIONS:
        return {
            "success": False,
            "offline": True,
            "api_calls": 0,
            "error": f"Unknown action '{params.action}'. Use one of: {', '.join(_VALID_ACTIONS)}.",
        }

    root = Path(params.source_root)

    if action == "page":
        if not (root / _PAGE_GRAPH_FILE).is_file():
            return _missing_analysis(root)
        answer = _answer_page(root, params.name)
    else:
        cross_refs = _read_json(root / _CROSS_REFS_FILE)
        if cross_refs is None:
            return _missing_analysis(root)
        if action == "uses":
            answer = _answer_uses(cross_refs, params.name)
        elif action == "used_by":
            answer = _answer_used_by(cross_refs, params.name)
        else:  # impact
            answer = _answer_impact(cross_refs, params.name)

    return {
        "success": True,
        "offline": True,
        "api_calls": 0,
        "action": action,
        "name": params.name,
        **answer,
    }
