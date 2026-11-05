"""Is the FEATURE behind a table on? Decided by the tool, at call time.

A read that failed or came back empty has three very different causes, and the
model was left to guess between them:

- the feature is not installed (Event Management off: ``em_alert`` does not
  exist, and suggesting ``sysevent_alert`` sends the caller to the wrong data);
- the session is not permitted (the table exists, the ACL refuses);
- the name is wrong (a typo).

And on a lab instance the Discovery and Service Mapping tables EXIST with both
plugins off, so "table present, 0 rows" was printed for a feature that is not
there. Table presence is therefore never the primary signal: plugin and app
state is (``v_plugin`` / ``sys_store_app``), read back per call, with the
domain map in ``config/capabilities.yaml``.

A verdict is only as strong as what was read:

- ``present`` — a listed plugin/app row came back active;
- ``absent`` — rows came back and none is active;
- ``undetermined`` — nothing readable came back (catalog not readable by this
  auth or role, or no row for any listed id). Never collapsed into absent.

Only ``present`` is memoised. The accusing answer is re-read every time — the
same rule as ``query_fields.unknown_query_fields``: a cached "it is off" is a
stale copy of a server fact, and it would be spent on the one answer that tells
the caller to stop.
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.utils import json_fast

logger = logging.getLogger(__name__)

_PRESENT_MEMO: Dict[Tuple[str, str], Dict[str, Any]] = {}
_MEMO_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _domains() -> Dict[str, Dict[str, Any]]:
    from importlib.resources import files

    import yaml

    try:
        text = files("servicenow_mcp.config").joinpath("capabilities.yaml").read_text("utf-8")
        loaded = yaml.safe_load(text) or {}
    except Exception as exc:  # a broken map must not break every read
        logger.warning("capabilities.yaml unreadable: %s — feature verdicts disabled", exc)
        return {}
    domains = loaded.get("domains") or {}
    return {str(k): v for k, v in domains.items() if isinstance(v, dict)}


def domain_for_table(table: str) -> Optional[str]:
    """The feature domain that owns ``table``, or None. Longest match wins."""
    best: Optional[Tuple[int, str]] = None
    for key, spec in _domains().items():
        for pattern in spec.get("tables") or []:
            pattern = str(pattern)
            hit = table.startswith(pattern) if pattern.endswith("_") else table == pattern
            if hit and (best is None or len(pattern) > best[0]):
                best = (len(pattern), key)
    return best[1] if best else None


def tables_exist_without_feature(domain: str) -> bool:
    return bool(_domains().get(domain, {}).get("tables_exist_without_feature"))


def _read_rows(
    config: Any, auth_manager: Any, table: str, key: str, ids: List[str]
) -> Optional[List[Dict[str, Any]]]:
    """``[{key, active}]`` for ``ids``, or None when the read did not come back."""
    try:
        resp = auth_manager.make_request(
            "GET",
            f"{config.instance_url}/api/now/table/{table}",
            params={
                "sysparm_query": f"{key}IN" + ",".join(ids),
                "sysparm_fields": f"{key},active",
                "sysparm_limit": len(ids) + 5,
            },
            timeout=getattr(config, "timeout", 15),
        )
        if getattr(resp, "status_code", 200) >= 400:
            return None
        body = json_fast.loads(resp.content) if resp.content else resp.json()
        result = body.get("result") if isinstance(body, dict) else None
    except Exception:
        return None
    return result if isinstance(result, list) else None


def _is_active(value: Any) -> bool:
    # v_plugin answers "active"/"inactive"; sys_store_app answers "true"/"false".
    return str(value).strip().lower() in {"active", "true", "1"}


def feature_state(config: Any, auth_manager: Any, domain: str) -> Dict[str, Any]:
    """``{domain, label, state, evidence|because}`` for one feature domain."""
    spec = _domains().get(domain)
    if not spec:
        return {"domain": domain, "state": "undetermined", "because": "unknown feature domain"}
    memo_key = (str(getattr(config, "instance_url", "")), domain)
    with _MEMO_LOCK:
        if memo_key in _PRESENT_MEMO:
            return dict(_PRESENT_MEMO[memo_key])

    label = spec.get("label") or domain
    sources = [
        ("v_plugin", "id", [str(i) for i in spec.get("plugins") or []]),
        ("sys_store_app", "scope", [str(s) for s in spec.get("apps") or []]),
    ]
    seen_off: List[str] = []
    unreadable: List[str] = []
    for table, key, ids in sources:
        if not ids:
            continue
        rows = _read_rows(config, auth_manager, table, key, ids)
        if rows is None:
            unreadable.append(table)
            continue
        for row in rows:
            name = str(row.get(key) or "")
            if _is_active(row.get("active")):
                verdict = {
                    "domain": domain,
                    "label": label,
                    "state": "present",
                    "evidence": f"{table} {name} is active",
                }
                with _MEMO_LOCK:
                    _PRESENT_MEMO[memo_key] = verdict
                return dict(verdict)
            if name:
                seen_off.append(f"{table} {name}")

    if seen_off:
        return {
            "domain": domain,
            "label": label,
            "state": "absent",
            "evidence": ", ".join(seen_off) + " — read back, not active",
        }
    if unreadable:
        because = (
            f"{' and '.join(unreadable)} not readable by this session (role or auth type), "
            "so whether the feature is on is unknown"
        )
    else:
        because = "none of the listed plugin/app ids is in this instance's catalog"
    return {"domain": domain, "label": label, "state": "undetermined", "because": because}


def table_feature(config: Any, auth_manager: Any, table: str) -> Optional[Dict[str, Any]]:
    """``feature_state`` for the domain owning ``table``; None if no domain owns it."""
    domain = domain_for_table(table)
    if domain is None:
        return None
    return feature_state(config, auth_manager, domain)


def forget_features() -> None:
    """Drop memoised verdicts (tests, or after a plugin was activated)."""
    with _MEMO_LOCK:
        _PRESENT_MEMO.clear()


__all__ = [
    "domain_for_table",
    "feature_state",
    "forget_features",
    "table_feature",
    "tables_exist_without_feature",
]
