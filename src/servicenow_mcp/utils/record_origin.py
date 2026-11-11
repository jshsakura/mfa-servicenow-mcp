"""Who delivered a record: ServiceNow, another vendor, or this customer.

Editing a record ServiceNow ships (a baseline Service Portal widget, an
Employee Center header) makes it a customer customization: the next upgrade
SKIPS it, and the record stops receiving ServiceNow's fixes. That is sometimes
the right call, so nothing here blocks — but it should be a decision, made
knowing it, not a side effect of pushing a file.

The signal is the record's PACKAGE, measured on a live instance with Employee
Center installed:

- ``sys_plugins`` package                      -> ServiceNow (platform plugin)
- ``sys_store_app`` package, scope vendor = ServiceNow -> ServiceNow (store app)
- ``sys_store_app`` package, any other vendor  -> that vendor
- ``sys_app`` package (built on the instance)  -> customer
- the Global package (``sys_package=global``)  -> customer

Rejected signals, also measured: ``sp_widget.servicenow`` is false on 121 of
296 widgets, Employee Center's own among them; baseline widgets carry no
``sys_update_version`` rows. Lineage is not a signal either — the platform
records no "cloned from", so a clone is judged by the package it now lives in,
which is the customer's.

A package that could not be read is ``undetermined``, never ``customer``:
"could not find out" must not read as "it is ours".
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

SERVICENOW = "servicenow"
VENDOR = "vendor"
CUSTOMER = "customer"
UNDETERMINED = "undetermined"

# Dot-walked onto any sys_metadata read; the Table API returns them as flat keys
# ("sys_package.sys_class_name"). Names proven against a live schema.
ORIGIN_FIELDS = (
    "sys_class_name",
    "sys_package",
    "sys_package.sys_class_name",
    "sys_package.name",
    "sys_scope.vendor",
)


def _plain(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value") or value.get("display_value") or ""
    return str(value or "").strip()


def classify(row: Dict[str, Any]) -> Dict[str, Any]:
    """Verdict for one record row that was read with ``ORIGIN_FIELDS``."""
    package = _plain(row.get("sys_package"))
    package_class = _plain(row.get("sys_package.sys_class_name"))
    package_name = _plain(row.get("sys_package.name"))
    vendor = _plain(row.get("sys_scope.vendor"))
    out: Dict[str, Any] = {"package": package_name or package, "package_class": package_class}
    record_class = _plain(row.get("sys_class_name"))
    if record_class:
        out["record_class"] = record_class
    if vendor:
        out["vendor"] = vendor

    if package == "global":
        out["verdict"] = CUSTOMER
    elif package_class == "sys_plugins":
        out["verdict"] = SERVICENOW
    elif package_class == "sys_store_app":
        if not vendor:
            out["verdict"] = UNDETERMINED
            out["reason"] = "store app with no readable vendor"
        elif vendor.lower() == "servicenow":
            out["verdict"] = SERVICENOW
        else:
            out["verdict"] = VENDOR
    elif package_class == "sys_app":
        out["verdict"] = CUSTOMER
    else:
        out["verdict"] = UNDETERMINED
        out["reason"] = (
            f"package class {package_class!r} is not a known kind"
            if package_class
            else "package not readable"
        )
    return out


def record_origin(config: Any, auth_manager: Any, table: str, sys_id: str) -> Dict[str, Any]:
    """Live verdict for one record. A failed read is ``undetermined`` with the reason."""
    from servicenow_mcp.tools.sn_api import _is_auth_error, sn_query_page

    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=f"sys_id={sys_id}",
            fields="sys_id," + ",".join(ORIGIN_FIELDS),
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 - reported as undetermined, never as clean
        if _is_auth_error(exc):
            raise
        return {"verdict": UNDETERMINED, "reason": f"origin read failed: {exc}"}
    if not rows:
        return {"verdict": UNDETERMINED, "reason": "record not returned"}
    return classify(rows[0])


def summarize(verdicts: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for v in verdicts:
        key = str(v.get("verdict") or UNDETERMINED)
        counts[key] = counts.get(key, 0) + 1
    return counts


def servicenow_owned(items: List[Dict[str, Any]], key: str = "origin") -> List[Dict[str, Any]]:
    return [i for i in items if (i.get(key) or {}).get("verdict") == SERVICENOW]


def clone_call(record_class: str, sys_id: str, record_id: Optional[str]) -> Optional[str]:
    """The call that makes this record the customer's own, where one exists.

    Keyed on the record's own class, not the folder it was downloaded into: a
    header/footer fetched through the widget table is still a header/footer, and
    cloning it as a plain widget would drop it out of the theme.
    """
    action = {"sp_widget": "clone_widget", "sp_header_footer": "clone_header_footer"}.get(
        record_class
    )
    if not action:
        return None
    # A widget with no technical id is reported by its name ("Header Menu"); an
    # id with spaces is not one a page can reference, so fold it to a slug.
    slug = re.sub(r"[^a-z0-9_]+", "-", str(record_id or "").lower()).strip("-")
    new_id = f"{slug or 'widget'}-custom"
    return (
        f"manage_portal_component(action='{action}', source='{sys_id}', "
        f"new_id='{new_id}', name='<name>', scope='<your app scope or global>')"
    )
