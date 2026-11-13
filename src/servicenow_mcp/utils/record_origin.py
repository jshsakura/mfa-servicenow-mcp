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

A package is where a record LIVES, not who made it. A customer can create a
record inside a ServiceNow store app's scope, and the package alone then calls
it ServiceNow's — the push gate asked to approve "editing baseline" for a widget
that no upgrade has a copy of. So a ServiceNow verdict on a store app is checked
against the record's own history (:func:`_born_here`, live only): created on
this instance means its first tracked version is a local update set's, written
by the creator within seconds of creation. Measured on a lab instance:

- created here (a dictionary entry via REST): first version 6 s after creation,
  ``source_table=sys_update_set``, same user;
- delivered (store-app and plugin records): no version rows at all, whether the
  install kept the payload's creation date (2021 on a 2026 instance) or stamped
  its own;
- moved in by update set: the source's creation date (2022) and a version at
  commit time — not born here, so it stays gated. The expensive answer.

Absence of that proof is not proof of delivery, but it is the case the gate
was built for, so it keeps asking. "No version rows" is NOT the customer
signal: an untouched baseline record has none either.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

SERVICENOW = "servicenow"
VENDOR = "vendor"
CUSTOMER = "customer"
UNDETERMINED = "undetermined"

# Dot-walked onto any sys_metadata read; the Table API returns them as flat keys
# ("sys_package.sys_class_name"). Names proven against a live schema.
ORIGIN_FIELDS = (
    "sys_class_name",
    "sys_update_name",
    "sys_created_on",
    "sys_created_by",
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


# A record's insert and its first version are one save; 6 s was the slowest
# measured (a dictionary insert, which builds a column first).
_BIRTH_WINDOW_S = 60
_VERSION_PAGE = 100


def _when(value: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(_plain(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _born_here(config: Any, auth_manager: Any, row: Dict[str, Any]) -> Dict[str, Any]:
    """Whether this record was created on this instance, from its version history.

    ``{"born_here": True, ...}`` only with the proof in hand; otherwise False with
    what was missing. A failed or capped read proves nothing and says so.
    """
    from servicenow_mcp.tools.sn_api import _is_auth_error, sn_query_page

    update_name = _plain(row.get("sys_update_name"))
    created = _when(row.get("sys_created_on"))
    creator = _plain(row.get("sys_created_by"))
    if not (update_name and created and creator):
        return {"born_here": False, "why": "creation stamp or update name not readable"}
    try:
        versions, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_update_version",
            # Range cut client-side: an encoded date filter that the server
            # misreads returns no rows, which would read as "no proof" at best.
            query=f"name={update_name}^ORDERBYsys_created_on",
            fields="sys_created_on,sys_created_by,source_table",
            limit=_VERSION_PAGE,
            offset=0,
            display_value=False,
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 - no proof, said as such
        if _is_auth_error(exc):
            raise
        return {"born_here": False, "why": f"version history not readable: {exc}"}
    for version in versions:
        at = _when(version.get("sys_created_on"))
        if (
            at is not None
            and 0 <= (at - created).total_seconds() <= _BIRTH_WINDOW_S
            and _plain(version.get("source_table")) == "sys_update_set"
            and _plain(version.get("sys_created_by")) == creator
        ):
            return {
                "born_here": True,
                "why": (
                    f"created on this instance by {creator} at {_plain(row.get('sys_created_on'))}; "
                    "its first version is in a local update set"
                ),
            }
    if not versions:
        return {
            "born_here": False,
            "why": "no version history (an untouched baseline record has none)",
        }
    capped = len(versions) >= _VERSION_PAGE
    return {
        "born_here": False,
        "why": "no local version at creation"
        + (f" in the {_VERSION_PAGE} versions read (history is longer)" if capped else ""),
    }


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
    out = classify(rows[0])
    # A plugin's records are the platform's; a store app's scope is one a
    # customer can build in. Only the latter is asked whose the record is.
    if out.get("verdict") == SERVICENOW and out.get("package_class") == "sys_store_app":
        birth = _born_here(config, auth_manager, rows[0])
        if birth["born_here"]:
            out["verdict"] = CUSTOMER
            out["created_in_vendor_scope"] = birth["why"]
        else:
            out["delivery_basis"] = f"package is a ServiceNow store app; {birth['why']}"
    return out


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
