"""Update set (sys_update_set) service layer.

Business logic for create / update / commit / move_file / remove_file.
``manage_changeset`` in tools/changeset_tools.py is the sole public entry point.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import count_response, invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

# What to read when the server refuses a write to an update set. The refusal is
# the server's; WHY it refused is in its ACLs, and those are readable — so the
# answer to a 403 is a lookup, not "this cannot be done over MCP".
_ACL_LOOKUPS = (
    # Field names as SOURCE_CONFIG['acl'] uses them (proven live). `operation` is
    # read, not filtered on: its column type differs between releases, and a
    # filter the server cannot apply is DROPPED, not refused.
    "sn_query(table='sys_security_acl', query='name=sys_update_set^ORnameSTARTSWITHsys_update_set."
    "^active=true', fields='name,operation,condition,admin_overrides,advanced,sys_id')",
    # Required roles are rows in the m2m table, not a column on the ACL.
    "sn_query(table='sys_security_acl_role', query='sys_security_acl.name=sys_update_set"
    "^ORsys_security_acl.nameSTARTSWITHsys_update_set.', "
    "fields='sys_security_acl.name,sys_security_acl.operation,sys_user_role.name')",
)


def _write_failure(verb: str, changeset_id: str, exc: Exception) -> Dict[str, Any]:
    """The server's own words, not just the status line — and, for a refusal, where to look."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    detail = ""
    if response is not None:
        try:
            err = (response.json() or {}).get("error") or {}
            detail = " — ".join(str(x) for x in (err.get("message"), err.get("detail")) if x)
        except Exception:  # noqa: BLE001 - a non-JSON body is reported as text
            detail = str(getattr(response, "text", "") or "")[:300]
    out: Dict[str, Any] = {
        "success": False,
        "message": f"Error {verb} changeset: {exc}" + (f" ({detail})" if detail else ""),
        "http_status": status,
    }
    if detail:
        out["server_message"] = detail
    if status in (401, 403):
        out["error"] = "WRITE_REFUSED"
        out["refused_by"] = (
            "ServiceNow refused this write, so nothing changed. Two things answer 403: an "
            "ACL/role check, or a business rule that aborted the save — server_message is "
            "the server's own reason and usually names which. It is a rule on the instance, "
            "not a missing MCP capability: do not tell the user it cannot be done over MCP."
        )
        out["next"] = [
            "Quote server_message to the user first; it often says the reason outright.",
            "Business rules that can abort it: get_table_automation(table='sys_update_set', "
            "operation='update')",
            f"ACLs on the table: {_ACL_LOOKUPS[0]}",
            f"Roles those ACLs require: {_ACL_LOOKUPS[1]}",
            f"The set itself: manage_changeset(action='get', changeset_id='{changeset_id}')",
        ]
    elif status == 404:
        # Measured on lab: a user without read access to the set gets 404 "No Record
        # found — Record doesn't exist or ACL restricts the record retrieval". So a
        # 404 is not proof the set is gone — say both, never just "not found".
        out["error"] = "NOT_FOUND_OR_HIDDEN"
        out["refused_by"] = (
            "ServiceNow answers 404 both when the set does not exist and when a read ACL "
            "hides it from this session's user. Nothing changed. Do not tell the user the "
            "set is gone until it is checked by someone who can read it."
        )
        out["next"] = [
            f"The set as this session sees it: manage_changeset(action='get', changeset_id='{changeset_id}')",
            "Who this session is: manage_session_context(action='get')",
            f"Read ACLs on the table: {_ACL_LOOKUPS[0]}",
        ]
    return out


# `developer` is NOT a sys_update_set column — probed on a live instance, a
# filter on it returns all 177 rows, i.e. the condition is dropped, and a write
# setting it is accepted and ignored. Update sets record their author in
# sys_created_by, which the server sets.
_CHANGESET_UPDATE_FIELDS = ("name", "description", "state")

# An entry's `payload` is the whole record serialized as XML. Measured on a live
# set of 100 entries: 13.1 MB read, 89% of it payload, against 37.6 KB for these
# columns, so the full read was cut by the response budget before the caller saw
# the entry ids it came for. The listing reads these; include_payload reads all.
ENTRY_LISTING_FIELDS = (
    "sys_id,name,target_name,type,table,action,application,category,comments,"
    "remote_update_set,replace_on_upgrade,sys_created_by,sys_created_on,"
    "sys_updated_by,sys_updated_on"
)
ENTRY_LISTING_LIMIT = 100


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    application: str,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new update set. The server records its author in sys_created_by."""
    data: Dict[str, Any] = {"name": name, "application": application}
    if description:
        data["description"] = description
    url = f"{config.api_url}/table/sys_update_set"
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("POST", url, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="sys_update_set")
        return {
            "success": True,
            "message": "Changeset created successfully",
            "changeset": result["result"],
        }
    except Exception as e:
        logger.error("Error creating changeset: %s", e)
        return {"success": False, "message": f"Error creating changeset: {str(e)}"}


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    changeset_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    state: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update an existing update set. Supports dry-run preview."""
    if state and state.strip().lower() == "complete":
        # Completing goes through commit: it shows what the set holds, whose work
        # is in it, and where the session lands — a bare state PATCH checks none.
        return {
            "success": False,
            "error": "USE_COMMIT",
            "message": "Completing an update set is action='commit', not update: commit "
            "lists the set's entries and authors first and verifies the stored state.",
            "next": [
                f"manage_changeset(action='commit', changeset_id='{changeset_id}', dry_run=True)"
            ],
        }
    data: Dict[str, Any] = {}
    if name:
        data["name"] = name
    if description:
        data["description"] = description
    if state:
        data["state"] = state
    if not data:
        return {"success": False, "message": "No fields to update"}

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sys_update_set",
            sys_id=changeset_id,
            proposed=data,
            identifier_fields=["name", "state", "application"],
        )

    url = f"{config.api_url}/table/sys_update_set/{changeset_id}"
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("PATCH", url, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="sys_update_set")
        return {
            "success": True,
            "message": "Changeset updated successfully",
            "changeset": result["result"],
        }
    except Exception as e:
        logger.error("Error updating changeset: %s", e)
        return _write_failure("updating", changeset_id, e)


def _commit_preflight(
    config: ServerConfig, auth_manager: AuthManager, changeset_id: str
) -> Dict[str, Any]:
    """Everything the user should see before a set is closed — each part read live.

    A part that could not be read is reported as unread and stops the commit:
    "no other authors" may only be said when the author counts came back.
    """
    from servicenow_mcp.tools.sn_api import _authenticated_user, sn_count_by_group

    invalidate_query_cache(table="sys_update_set")
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_update_set",
        query=f"sys_id={changeset_id}",
        fields="sys_id,name,state,application,is_default,description",
        limit=1,
        offset=0,
        fail_silently=False,
    )
    if not rows:
        return {
            "refusal": _refuse(
                f"No update set {changeset_id} was returned (missing or not readable)."
            )
        }
    us = rows[0]
    info: Dict[str, Any] = {
        "set": {
            "sys_id": changeset_id,
            "name": us.get("name"),
            "state": us.get("state"),
            "application": _ref_value(us.get("application")),
        },
        "description": us.get("description") or "",
    }
    if str(us.get("is_default")).lower() == "true":
        info["refusal"] = _refuse(
            f"'{us.get('name')}' is a Default update set. It is the catch-all every session "
            "falls back to; it is not completed to ship work. Move the entries to a named set "
            "(action='move_file') and complete that."
        )
        return info

    query = f"update_set={changeset_id}"
    by_type = sn_count_by_group(config, auth_manager, "sys_update_xml", query, "type")
    created = sn_count_by_group(config, auth_manager, "sys_update_xml", query, "sys_created_by")
    updated = sn_count_by_group(config, auth_manager, "sys_update_xml", query, "sys_updated_by")
    if by_type is None or created is None or updated is None:
        info["refusal"] = _refuse(
            "The set's entries could not be counted, so who they belong to is not known. "
            "Nothing was changed. Read them with action='get' and retry."
        )
        return info
    info["entries"] = sum(by_type.values())
    info["entries_by_type"] = dict(sorted(by_type.items(), key=lambda kv: -kv[1])[:15])

    me = _authenticated_user(config, auth_manager, allow_live=True)
    authors = {a for a in list(created) + list(updated)}
    others = sorted(
        {(a or _UNKNOWN_AUTHOR) for a in authors if me is None or not a or a.lower() != me.lower()},
        key=str.lower,
    )
    info["you"] = me
    if others:
        info["other_authors"] = others
        if me is None:
            info["other_authors_note"] = (
                "Your own user could not be confirmed, so no author can be treated as you."
            )

    current = None
    try:
        from servicenow_mcp.tools.session_context_tools import get_current_update_set

        current = get_current_update_set(config, auth_manager)
    except Exception:  # noqa: BLE001 - reported as unknown below, never as "not current"
        current = None
    if current and current.get("sys_id"):
        info["is_current"] = current.get("sys_id") == changeset_id
    else:
        info["is_current"] = "unknown"
    return info


def commit(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    changeset_id: str,
    commit_message: Optional[str] = None,
    confirm_other_author: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Mark an update set complete — after showing what it holds and whose it is."""
    try:
        info = _commit_preflight(config, auth_manager, changeset_id)
    except Exception as exc:  # noqa: BLE001
        return _refuse(f"The update set could not be read, so nothing was changed: {exc}")
    if "refusal" in info:
        return {**info.pop("refusal"), "preflight": info}

    state = str(info["set"].get("state") or "")
    if state == "complete":
        return {
            "success": True,
            "written": False,
            "message": f"'{info['set']['name']}' is already complete. Nothing was changed.",
            "preflight": info,
        }
    if state != _IN_PROGRESS:
        return _refuse(
            f"'{info['set']['name']}' is '{state}', not in progress; only an in-progress set "
            "is completed here.",
            preflight=info,
        )

    notes: List[str] = []
    if info["entries"] == 0:
        notes.append("The set is EMPTY — completing it ships nothing.")
    if info["is_current"] is True:
        notes.append(
            "This is your session's CURRENT update set. Once complete, the session captures "
            "into Default: choose or create a set before the next change."
        )
    elif info["is_current"] == "unknown":
        notes.append("Whether this is your current update set could not be read.")

    required = info.get("other_authors") or []
    approvals: Dict[str, Any] = {"confirm": "approve", "confirm_publish": "approve"}
    unapproved: List[str] = []
    if required:
        approvals["confirm_other_author"] = ",".join(required)
        unapproved = [a for a in required if a.lower() not in _approved_names(confirm_other_author)]
        notes.append(
            "It holds changes by " + ", ".join(repr(a) for a in required) + ". Completing it "
            "ships their work too; the user must agree by name."
        )

    if dry_run or unapproved:
        out: Dict[str, Any] = {
            "success": not unapproved,
            "dry_run": dry_run,
            "written": False,
            "preflight": info,
            "notes": notes,
            "approvals_needed": approvals,
            "message": (
                "Show this to the user. Only on their go-ahead: manage_changeset(action='commit', "
                f"changeset_id='{changeset_id}', "
                + ", ".join(f"{k}='{v}'" for k, v in approvals.items())
                + ")."
            ),
        }
        if unapproved:
            out["error"] = "OTHER_AUTHORS_NOT_APPROVED"
        return out

    data: Dict[str, Any] = {"state": "complete"}
    if commit_message:
        # Appended, never replacing what the set already says about itself.
        prior = str(info.get("description") or "").rstrip()
        data["description"] = f"{prior}\n\n{commit_message}" if prior else commit_message

    url = f"{config.api_url}/table/sys_update_set/{changeset_id}"
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"
    try:
        response = auth_manager.make_request("PATCH", url, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
    except Exception as e:
        logger.error("Error committing changeset: %s", e)
        return {**_write_failure("committing", changeset_id, e), "preflight": info}
    invalidate_query_cache(table="sys_update_set")
    stored = str(((result or {}).get("result") or {}).get("state") or "")
    out = {
        "success": stored == "complete",
        "written": True,
        "message": (
            f"'{info['set']['name']}' is complete ({info['entries']} entries)."
            if stored == "complete"
            else f"The write returned state '{stored}', not complete — a business rule may "
            "have changed it. Read the set before treating it as done."
        ),
        "changeset": {"sys_id": changeset_id, "name": info["set"]["name"], "state": stored},
        "preflight": info,
    }
    if info["is_current"] is True:
        try:
            from servicenow_mcp.tools.session_context_tools import get_current_update_set

            now = get_current_update_set(config, auth_manager) or {}
            out["current_update_set_now"] = {"sys_id": now.get("sys_id"), "name": now.get("name")}
        except Exception:  # noqa: BLE001
            out["current_update_set_now"] = "could not be read"
        out["next"] = (
            "The session now captures into the set above (usually Default). Choose or create "
            "the next set before any change: manage_session_context(action='set_update_set', ...)."
        )
    return out


def get(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    changeset_id: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    state: Optional[str] = None,
    application: Optional[str] = None,
    timeframe: Optional[str] = None,
    query: Optional[str] = None,
    count_only: bool = False,
    include_payload: bool = False,
) -> Dict[str, Any]:
    """Fetch a single changeset (detail) or list with filters."""
    if changeset_id:
        try:
            records, _ = sn_query_page(
                config,
                auth_manager,
                table="sys_update_set",
                query=f"sys_id={changeset_id}",
                fields="",
                limit=1,
                offset=0,
            )
            if not records:
                return {"success": False, "message": f"Changeset not found: {changeset_id}"}
            # Loud on failure: a silenced read would come back as "0 entries".
            changes, total = sn_query_page(
                config,
                auth_manager,
                table="sys_update_xml",
                query=f"update_set={changeset_id}",
                fields="" if include_payload else ENTRY_LISTING_FIELDS,
                limit=ENTRY_LISTING_LIMIT,
                offset=0,
                orderby="-sys_updated_on",
                fail_silently=False,
            )
            result: Dict[str, Any] = {
                "success": True,
                "changeset": records[0],
                "changes": changes,
                "change_count": len(changes),
            }
            if total is None or total > len(changes):
                result["change_total"] = total
                result["complete"] = False
                result["more"] = (
                    f"Listed the {len(changes)} most recently updated of "
                    f"{total if total is not None else 'an unknown number of'} entries. "
                    f"Read the rest with sn_query(table='sys_update_xml', "
                    f"query='update_set={changeset_id}', fields='{ENTRY_LISTING_FIELDS}', "
                    f"offset={len(changes)})."
                )
            if not include_payload:
                result["payload"] = (
                    "Each entry's payload (the full record XML) is left out. Pass "
                    "include_payload=true, or read one entry with sn_query(table='sys_update_xml', "
                    "query='sys_id=<entry>', fields='payload')."
                )
            return result
        except Exception as e:
            logger.error("Error getting changeset details: %s", e)
            return {"success": False, "message": f"Error getting changeset details: {str(e)}"}

    query_parts: List[str] = []
    if state:
        query_parts.append(f"state={state}")
    if application:
        query_parts.append(f"application={application}")
    if timeframe:
        if timeframe == "recent":
            query_parts.append(
                "sys_created_onONLast 7 days@javascript:gs.beginningOfLast7Days()@javascript:gs.endOfToday()"
            )
        elif timeframe == "last_week":
            query_parts.append(
                "sys_created_onONLast week@javascript:gs.beginningOfLastWeek()@javascript:gs.endOfLastWeek()"
            )
        elif timeframe == "last_month":
            query_parts.append(
                "sys_created_onONLast month@javascript:gs.beginningOfLastMonth()@javascript:gs.endOfLastMonth()"
            )
    if query:
        query_parts.append(query)
    query_str = "^".join(query_parts) if query_parts else ""

    if count_only:
        return count_response(config, auth_manager, "sys_update_set", query_str, what="update sets")

    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_update_set",
            query=query_str,
            fields="",
            limit=limit,
            offset=offset,
        )
        return {"success": True, "changesets": records, "count": len(records)}
    except Exception as e:
        logger.error("Error listing changesets: %s", e)
        return {"success": False, "message": f"Error listing changesets: {str(e)}"}


# ---------------------------------------------------------------------------
# move_file / remove_file — take a captured change out of an update set
# ---------------------------------------------------------------------------
#
# A wrong edit lands in the current update set as a sys_update_xml row, and the
# only ways out were the ServiceNow UI or sn_write (deliberately unpackaged).
# These two actions are that missing tool, built so that nothing it reports is a
# guess:
#
#   - entries are named by sys_id only, at most MAX_ENTRY_BATCH; no queries,
#     because a query whose condition the server drops selects the whole table
#   - the source set is read live and must be in progress; every entry must
#     belong to it, or the whole batch is refused before anything is written
#   - a move needs a target that is in progress, in the same application, and
#     holds no entry for the same record already (two versions of one record in
#     one set leave the commit to decide which wins)
#   - an entry someone else captured needs their name in confirm_other_author;
#     an author that cannot be read, or a session whose user cannot be resolved,
#     names nobody, so it needs naming too instead of passing as "yours"
#   - remove_file is not reversible here, so it needs confirm_remove=<the source
#     set's name> on top of confirm='approve'
#   - after writing, every entry is read back; "verified" is printed only when
#     that read came back and matched
#
# Every read here uses fail_silently=False and starts from an invalidated cache:
# an unread page must stop the call, never pass as "no such entry" or "no clash".

MAX_ENTRY_BATCH = 20
_IN_PROGRESS = "in progress"
_ENTRY_FIELDS = (
    "sys_id,name,target_name,type,action,update_set,application,sys_created_by,sys_updated_by"
)
_SET_FIELDS = "sys_id,name,state,application"
_UNKNOWN_AUTHOR = "unknown"

RECORD_UNCHANGED_NOTE = (
    "Only the update set changed. The record itself still holds the edit on this "
    "instance; this decides what the update set carries to the next one. To undo "
    "the edit itself, change the record back, which captures a new entry."
)


def _refuse(message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "written": False, "message": message, **extra}


def _ref_value(value: Any) -> str:
    """Raw value of a reference field, whatever shape the read returned."""
    if isinstance(value, dict):
        value = value.get("value", "")
    return str(value or "").strip()


def _read_set(config: ServerConfig, auth_manager: AuthManager, sys_id: str) -> Dict[str, Any]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_update_set",
        query=f"sys_id={sys_id}",
        fields=_SET_FIELDS,
        limit=1,
        offset=0,
        fail_silently=False,
    )
    return rows[0] if rows else {}


def _read_entries(
    config: ServerConfig, auth_manager: AuthManager, entry_ids: List[str], fields: str
) -> List[Dict[str, Any]]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_update_xml",
        query="sys_idIN" + ",".join(entry_ids),
        fields=fields,
        limit=len(entry_ids) + 1,
        offset=0,
        fail_silently=False,
    )
    return rows


def _entry_authors(entry: Dict[str, Any], me: Optional[str]) -> List[str]:
    """Authors of this entry that are not provably the current user."""
    found = []
    for field in ("sys_created_by", "sys_updated_by"):
        who = str(entry.get(field) or "").strip()
        if not who:
            found.append(_UNKNOWN_AUTHOR)
        elif me is None or who.lower() != me.lower():
            found.append(who)
    return sorted(set(found), key=str.lower)


def _approved_names(value: Optional[str]) -> set:
    return {part.strip().lower() for part in str(value or "").split(",") if part.strip()}


def _describe(entry: Dict[str, Any], authors: List[str]) -> Dict[str, Any]:
    return {
        "sys_id": entry.get("sys_id"),
        "record": entry.get("target_name") or entry.get("name"),
        "type": entry.get("type"),
        "action": entry.get("action"),
        "created_by": entry.get("sys_created_by"),
        "updated_by": entry.get("sys_updated_by"),
        "other_authors": authors,
    }


def change_entries(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    action: str,
    changeset_id: str,
    entry_ids: List[str],
    target_changeset_id: Optional[str] = None,
    confirm_remove: Optional[str] = None,
    confirm_other_author: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Move entries to another in-progress update set, or remove them from this one."""
    from servicenow_mcp.tools.sn_api import _authenticated_user

    moving = action == "move_file"
    ids = list(dict.fromkeys(entry_ids))
    invalidate_query_cache(table="sys_update_set")
    invalidate_query_cache(table="sys_update_xml")

    # 1. The source set, read live.
    try:
        source = _read_set(config, auth_manager, changeset_id)
    except Exception as exc:
        return _refuse(f"Could not read update set {changeset_id}, so nothing was changed: {exc}")
    if not source:
        return _refuse(f"Update set {changeset_id} was not found. Nothing was changed.")
    # Compare against the id the server returned, not the one typed in.
    changeset_id = str(source.get("sys_id") or changeset_id)
    source_name = str(source.get("name") or "")
    source_app = _ref_value(source.get("application"))
    if str(source.get("state") or "").strip().lower() != _IN_PROGRESS:
        return _refuse(
            f"Update set '{source_name}' is '{source.get('state')}', not in progress, so its "
            "entries are left alone. If the user wants to change it anyway, reopen it first: "
            "manage_changeset(action='update', changeset_id=..., state='in progress')."
        )

    # 2. The target set (move only), read live.
    target: Dict[str, Any] = {}
    if moving:
        assert target_changeset_id is not None
        try:
            target = _read_set(config, auth_manager, target_changeset_id)
        except Exception as exc:
            return _refuse(
                f"Could not read the target update set {target_changeset_id}, so nothing was "
                f"changed: {exc}"
            )
        if not target:
            return _refuse(f"Target update set {target_changeset_id} was not found.")
        target_changeset_id = str(target.get("sys_id") or target_changeset_id)
        if target_changeset_id == changeset_id:
            return _refuse("The target is the same update set as the source.")
        if str(target.get("state") or "").strip().lower() != _IN_PROGRESS:
            return _refuse(
                f"Target update set '{target.get('name')}' is '{target.get('state')}', not in "
                "progress. Entries can only move into an open set."
            )
        target_app = _ref_value(target.get("application"))
        if not source_app or not target_app:
            return _refuse(
                "The application of the source or the target set could not be read, so it "
                "cannot be shown they match. Nothing was changed."
            )
        if source_app != target_app:
            return _refuse(
                f"'{source_name}' and '{target.get('name')}' belong to different applications. "
                "An entry can only move between sets of the same application."
            )

    # 3. The entries, read live; every one must belong to the source set.
    try:
        entries = _read_entries(config, auth_manager, ids, _ENTRY_FIELDS)
    except Exception as exc:
        return _refuse(f"Could not read the entries, so nothing was changed: {exc}")
    by_id = {str(e.get("sys_id")): e for e in entries}
    missing = [i for i in ids if i not in by_id]
    if missing:
        return _refuse(
            "These entries were not found, so the whole batch was refused: "
            + ", ".join(missing)
            + ". Find entry sys_ids with manage_changeset(action='get', changeset_id=...).",
            missing=missing,
        )
    elsewhere = [
        {"sys_id": i, "update_set": _ref_value(by_id[i].get("update_set"))}
        for i in ids
        if _ref_value(by_id[i].get("update_set")) != changeset_id
    ]
    if elsewhere:
        return _refuse(
            f"Some entries are not in '{source_name}', so the whole batch was refused.",
            not_in_source=elsewhere,
        )

    # 4. Move-only checks: same application per entry, and no clash in the target.
    if moving:
        foreign = [i for i in ids if _ref_value(by_id[i].get("application")) != target_app]
        if foreign:
            return _refuse(
                "Some entries belong to a different application than the target set (or "
                "their application could not be read), so the whole batch was refused.",
                wrong_application=foreign,
            )
        names = [str(by_id[i].get("name") or "") for i in ids]
        if not all(names):
            return _refuse(
                "Some entries have no readable name, so a clash in the target set cannot be "
                "ruled out. Nothing was changed."
            )
        try:
            clashes, _ = sn_query_page(
                config,
                auth_manager,
                table="sys_update_xml",
                query=f"update_set={target_changeset_id}^nameIN" + ",".join(names),
                fields="sys_id,name,target_name",
                limit=len(names) + 1,
                offset=0,
                fail_silently=False,
            )
        except Exception as exc:
            return _refuse(
                "Could not check the target set for entries of the same records, so nothing "
                f"was changed: {exc}"
            )
        if clashes:
            return _refuse(
                f"'{target.get('name')}' already holds an entry for some of these records. "
                "Moving would put two versions of one record in one set, and the commit would "
                "decide which wins. Resolve that first, for example by removing the one that "
                "should not ship.",
                already_in_target=[
                    {"sys_id": c.get("sys_id"), "record": c.get("target_name") or c.get("name")}
                    for c in clashes
                ],
            )

    # 5. Approvals.
    me = _authenticated_user(config, auth_manager, allow_live=True)
    described = []
    required_authors: set = set()
    for i in ids:
        authors = _entry_authors(by_id[i], me)
        required_authors.update(authors)
        described.append(_describe(by_id[i], authors))
    required = sorted(required_authors, key=str.lower)
    approvals: Dict[str, Any] = {}
    problems: List[str] = []
    if required:
        approvals["confirm_other_author"] = ",".join(required)
        unapproved = [a for a in required if a.lower() not in _approved_names(confirm_other_author)]
        if unapproved:
            who = (
                "Your own user could not be confirmed, so no author can be treated as you. "
                if me is None
                else ""
            )
            problems.append(
                who
                + "These entries carry changes by "
                + ", ".join(repr(a) for a in required)
                + ". Taking someone's work out of a set is their call too: ask the user, then "
                f"pass confirm_other_author='{approvals['confirm_other_author']}'."
            )
    if not moving:
        approvals["confirm_remove"] = source_name
        if str(confirm_remove or "").strip().lower() != source_name.strip().lower():
            problems.append(
                "Removing an entry cannot be undone through this tool. Moving it to a parking "
                "update set keeps it recoverable. If the user still wants it removed, pass "
                f"confirm_remove='{source_name}' (the source set's name)."
            )

    preview = {
        "action": action,
        "source": {"sys_id": changeset_id, "name": source_name},
        "target": ({"sys_id": target_changeset_id, "name": target.get("name")} if moving else None),
        "entries": described,
        "approvals_required": approvals,
        "note": RECORD_UNCHANGED_NOTE,
    }
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "written": False,
            "message": (
                f"Preview: {len(ids)} entr{'y' if len(ids) == 1 else 'ies'} would be "
                + (
                    f"moved to '{target.get('name')}'."
                    if moving
                    else f"removed from '{source_name}'."
                )
                + (" Still needed: " + " ".join(problems) if problems else "")
            ),
            **preview,
        }
    if problems:
        return _refuse(" ".join(problems), **preview)

    # 6. Write, one entry at a time; stop at the first failure.
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"
    done: List[str] = []
    failure: Optional[Dict[str, Any]] = None
    for i in ids:
        url = f"{config.api_url}/table/sys_update_xml/{i}"
        try:
            if moving:
                response = auth_manager.make_request(
                    "PATCH", url, json={"update_set": target_changeset_id}, headers=headers
                )
            else:
                response = auth_manager.make_request("DELETE", url, headers=headers)
            response.raise_for_status()
            done.append(i)
        except Exception as exc:
            # The status line alone ("403: Forbidden") left the caller guessing at
            # scope; the server's body usually says which rule refused it.
            told = _write_failure("writing an entry of", changeset_id, exc)
            failure = {"sys_id": i, "error": str(exc)}
            for key in ("http_status", "server_message", "error", "refused_by"):
                if told.get(key) is not None:
                    failure["reason" if key == "error" else key] = told[key]
            break
    invalidate_query_cache(table="sys_update_xml")

    # 7. Read back what was written.
    verification: Dict[str, Any] = {"determined": False, "mismatched": []}
    if done:
        try:
            after = {
                str(r.get("sys_id")): r
                for r in _read_entries(config, auth_manager, done, "sys_id,update_set")
            }
            if moving:
                mismatched = [
                    i
                    for i in done
                    if i not in after
                    or _ref_value(after[i].get("update_set")) != target_changeset_id
                ]
            else:
                mismatched = [i for i in done if i in after]
            verification = {"determined": True, "mismatched": mismatched}
        except Exception as exc:
            verification["error"] = f"Could not read the entries back: {exc}"

    verified = verification["determined"] and not verification["mismatched"] and not failure
    verb = "moved" if moving else "removed"
    if failure:
        message = (
            f"Stopped after {len(done)} of {len(ids)}: entry {failure['sys_id']} failed "
            f"({failure['error']}"
            + (
                f" — server said: {failure['server_message']}"
                if failure.get("server_message")
                else ""
            )
            + "). The rest were not touched."
        )
    elif not verification["determined"]:
        message = (
            f"{len(done)} entries were {verb}, but reading them back failed, so this is not "
            "verified. Check with manage_changeset(action='get', changeset_id=...)."
        )
    elif verification["mismatched"]:
        message = (
            f"The write was accepted, but {len(verification['mismatched'])} entries do not "
            f"read back as {verb}: " + ", ".join(verification["mismatched"])
        )
    else:
        message = f"{len(done)} entr{'y' if len(done) == 1 else 'ies'} {verb} and verified."
    return {
        "success": bool(done) and not failure and verified,
        "written": bool(done),
        "verified": verified,
        "message": message,
        "done": done,
        "not_done": [i for i in ids if i not in done],
        "failure": failure,
        "verification": verification,
        **preview,
    }
