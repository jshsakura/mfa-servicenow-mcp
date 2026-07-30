"""Verify a deployment XML against the live server — before and after import.

The gap this closes: ``update_remote_from_local`` enforces a live comparison
before it overwrites anything, but the XML deployment path had no equivalent.
An ``<unload>`` file could be hand-assembled from stale local copies, mailed on,
and recorded as deployed — with nothing anywhere able to answer either question
that matters:

  * *preflight* — is this file still what the live server holds? An XML captured
    before someone else's same-day edit will REVERT that edit on import. This is
    the check whose absence let a set of day-old XMLs get shipped as current.
  * *postflight* — did the import actually land? "Recorded as deployed, never
    imported" is invisible without asking the target directly.

Both are one question — "does the live record match this file?" — asked against
the instance that happens to be active. Run it while the SOURCE instance is
active to test the file's freshness; run it against the TARGET to see whether the
import landed. There is no cross-instance mode here on purpose: a registered tool
gets one instance's config, and reading the active one twice is clearer than
half-implementing ``compare_instances``.

Origin first: a file with no certificate from ``export_record_xml`` is not
provably a live export, and that is reported as ``unanchored`` before any network
call. ``allow_unanchored=True`` is a second approval, not an env switch — it
proceeds using the stamps embedded in the XML and brands the result
``origin_unverified``.
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.deploy_ledger import read_origin, record_applied
from servicenow_mcp.utils.registry import register_tool
from servicenow_mcp.utils.sync_anchor import normalize_for_hash

logger = logging.getLogger(__name__)

# Fields whose value legitimately differs between a captured export and a live
# record without meaning the CONTENT differs: audit stamps, update-set
# bookkeeping, and the per-instance packaging/domain columns. Comparing these
# would make every record read as changed.
VOLATILE_FIELDS = frozenset(
    {
        "sys_updated_on",
        "sys_updated_by",
        "sys_mod_count",
        "sys_created_on",
        "sys_created_by",
        "sys_update_name",
        "sys_customer_update",
        "sys_replace_on_upgrade",
        "sys_policy",
        "sys_scope",
        "sys_package",
        "sys_domain",
        "sys_domain_path",
    }
)

# Audit columns fetched alongside the compared fields, to date the live side.
_AUDIT_FIELDS = ("sys_updated_on", "sys_updated_by", "sys_mod_count")

# Work ceilings. Both are reported when they bite — a silent cap on a
# verification tool would read as "all clear" while covering only part of a file.
_MAX_RECORDS = 50
_MAX_FIELDS_PER_RECORD = 120

# Verdicts (one neutral vocabulary for both modes; the mode picks the wording).
MATCH = "match"  # live equals the file
LIVE_NEWER = "live_newer"  # differs AND live moved after the export -> import reverts
DIFFERS = "differs"  # differs, live not provably newer
MISSING = "missing"  # no such record on this instance
UNKNOWN = "unknown"  # could not be compared (unparseable block)

_BOOL_TRUE = frozenset({"true", "1"})
_BOOL_FALSE = frozenset({"false", "0"})


class VerifyDeploymentXmlParams(BaseModel):
    xml_path: str = Field(..., description="Deploy .xml built by export_record_xml")
    mode: Literal["preflight", "postflight"] = Field(
        default="preflight", description="preflight: before import. postflight: after import."
    )
    allow_unanchored: bool = Field(
        default=False, description="Second approval: verify an XML with no origin cert"
    )
    show_fields: bool = Field(
        default=True, description="List differing field NAMES per record (never bodies)"
    )


def _values_equal(xml_value: str, live_value: Any) -> bool:
    """EOL-insensitive value equality, with boolean spellings treated as equal.

    Uses the same normalized basis as the sync anchor so a script stored CRLF on
    one instance and LF on another never reads as a difference. Booleans are
    folded because the unload XML and the Table API do not agree on spelling
    ('true' vs '1'), and a spelling mismatch is not a deployment problem.
    """
    left = normalize_for_hash(xml_value if isinstance(xml_value, str) else "")
    right = normalize_for_hash(live_value if isinstance(live_value, str) else "")
    if left == right:
        return True
    low_left, low_right = left.strip().lower(), right.strip().lower()
    if low_left in _BOOL_TRUE and low_right in _BOOL_TRUE:
        return True
    if low_left in _BOOL_FALSE and low_right in _BOOL_FALSE:
        return True
    return False


def _parse_unload(path: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Read an <unload> file into per-record {table, sys_id, fields}.

    Accepts a bare <record_update> root too — a hand-built file often is one, and
    this tool exists precisely to look at files it did not write.
    """
    try:
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError) as exc:
        return [], f"Could not parse {path}: {exc}"
    # A single-record file is a bare <record_update>; both roots hold the record
    # blocks as direct children, so they read the same way from here.
    if root.tag.lower() not in ("unload", "record_update"):
        return [], f"Not a deploy XML: root is <{root.tag}>, expected <unload>."
    blocks = list(root)

    records: List[Dict[str, Any]] = []
    for block in blocks:
        # A <record_update> wrapper can appear per record inside <unload>.
        if block.tag.lower() == "record_update":
            inner = next(iter(block), None)
            if inner is None:
                continue
            block = inner
        fields: Dict[str, str] = {}
        truncated = 0
        for child in block:
            if child.tag in VOLATILE_FIELDS:
                continue
            if len(fields) >= _MAX_FIELDS_PER_RECORD:
                truncated += 1
                continue
            fields[child.tag] = child.text or ""
        record: Dict[str, Any] = {
            "table": block.tag,
            "sys_id": (block.findtext("sys_id") or "").strip(),
            "fields": fields,
            "xml_version": (block.findtext("sys_updated_on") or "").strip(),
            "xml_mod_count": (block.findtext("sys_mod_count") or "").strip(),
        }
        if truncated:
            record["fields_not_compared"] = truncated
        records.append(record)
    if not records:
        return [], f"No record blocks found in {path}."
    return records, None


def _fetch_live(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    sys_ids: List[str],
    fields: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Live rows for *sys_ids*, keyed by sys_id. Deliberately cache-bypassing.

    sn_query_page caches for 30s. A verification that answered from cache is the
    exact failure this tool exists to prevent — "confirmed deployed" from a read
    taken before the import. So the table's cache entries are dropped first.
    """
    from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page

    invalidate_query_cache(table=table)
    wanted = list(dict.fromkeys(["sys_id", *fields, *_AUDIT_FIELDS]))
    rows, _total = sn_query_page(
        config,
        auth_manager,
        table=table,
        query="sys_idIN" + ",".join(sys_ids),
        fields=",".join(wanted),
        limit=min(max(len(sys_ids), 1), 200),
        offset=0,
        display_value=False,
        no_count=True,
        fail_silently=False,
    )
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("sys_id") or "").strip()
        if key:
            out[key] = row
    return out


def _compare(record: Dict[str, Any], live: Optional[Dict[str, Any]], show_fields: bool) -> Dict:
    """One record's verdict against its live row."""
    result: Dict[str, Any] = {
        "table": record["table"],
        "sys_id": record["sys_id"],
        "xml_version": record.get("xml_version") or None,
    }
    if not record["sys_id"]:
        result["verdict"] = UNKNOWN
        result["note"] = "Block has no <sys_id> — cannot be matched to a live record."
        return result
    if live is None:
        result["verdict"] = MISSING
        result["note"] = "No such record on the active instance."
        return result

    live_version = str(live.get("sys_updated_on") or "").strip()
    result["live_version"] = live_version or None
    result["live_updated_by"] = str(live.get("sys_updated_by") or "").strip() or None

    differing = [
        name
        for name, value in record["fields"].items()
        if name != "sys_id" and not _values_equal(value, live.get(name))
    ]
    if not differing:
        result["verdict"] = MATCH
        return result

    # Both stamps are ServiceNow's "YYYY-MM-DD HH:MM:SS" UTC — lexicographic
    # comparison is chronological, so no parsing is needed (or wanted: a parse
    # failure here would silently downgrade the strongest signal we have).
    xml_version = record.get("xml_version") or ""
    result["verdict"] = LIVE_NEWER if live_version and live_version > xml_version else DIFFERS
    result["differing_field_count"] = len(differing)
    if show_fields:
        result["differing_fields"] = sorted(differing)[:25]
    if record.get("fields_not_compared"):
        result["fields_not_compared"] = record["fields_not_compared"]
    return result


@register_tool(
    "verify_deployment_xml",
    params=VerifyDeploymentXmlParams,
    description="Compare a deploy XML to the live server. preflight=would it revert work, postflight=did it land.",
    serialization="raw_dict",
    return_type=dict,
)
def verify_deployment_xml(
    config: ServerConfig, auth_manager: AuthManager, params: VerifyDeploymentXmlParams
) -> Dict[str, Any]:
    path = Path(params.xml_path).expanduser().resolve()
    if not path.is_file():
        return {"success": False, "message": f"No such file: {path}"}

    instance = (urlparse(config.instance_url).hostname or "instance").split(".")[0]
    origin = read_origin(path)
    if origin is None and not params.allow_unanchored:
        return {
            "success": False,
            "verdict": "unanchored",
            "xml_path": str(path),
            "message": (
                "This XML carries no origin certificate, so it is NOT provably a "
                "live export — a hand-assembled file looks identical to a real "
                "one. Rebuild it with export_record_xml (reads the live server), "
                "or pass allow_unanchored=true to verify it anyway using only the "
                "stamps inside the file."
            ),
        }

    records, err = _parse_unload(path)
    if err:
        return {"success": False, "xml_path": str(path), "message": err}

    dropped = max(0, len(records) - _MAX_RECORDS)
    records = records[:_MAX_RECORDS]

    by_table: Dict[str, List[str]] = {}
    for record in records:
        if record["sys_id"]:
            by_table.setdefault(record["table"], []).append(record["sys_id"])

    live_by_table: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for table, sys_ids in by_table.items():
        compared_fields = sorted(
            {name for r in records if r["table"] == table for name in r["fields"]}
        )
        try:
            live_by_table[table] = _fetch_live(
                config, auth_manager, table, sys_ids, compared_fields
            )
        except Exception as exc:  # noqa: BLE001 — surfaced in the result
            return {
                "success": False,
                "xml_path": str(path),
                "message": f"Live read of '{table}' failed: {exc}",
            }

    results = [
        _compare(
            record, live_by_table.get(record["table"], {}).get(record["sys_id"]), params.show_fields
        )
        for record in records
    ]

    counts: Dict[str, int] = {}
    for item in results:
        counts[item["verdict"]] = counts.get(item["verdict"], 0) + 1

    matched = counts.get(MATCH, 0)
    out: Dict[str, Any] = {
        "success": True,
        "mode": params.mode,
        "xml_path": str(path),
        "instance": instance,
        "record_count": len(results),
        "counts": counts,
        "records": results,
    }
    if origin:
        out["origin"] = {
            "source_instance": origin.get("source_instance"),
            "exported_at": origin.get("exported_at"),
            "records": len(origin.get("records") or []),
        }
        if origin.get("source_instance") and origin["source_instance"] != instance:
            out["origin"]["note"] = (
                f"Exported from '{origin['source_instance']}', comparing against "
                f"'{instance}' — expected for a postflight, suspicious for a "
                "freshness preflight."
            )
    else:
        out["origin_unverified"] = True
        out["origin_warning"] = (
            "No origin certificate: this file is not provably a live export. "
            "Verdicts below rest on stamps inside the file itself."
        )
    if dropped:
        out["records_not_checked"] = dropped
        out["truncation_warning"] = (
            f"Only the first {_MAX_RECORDS} of {len(results) + dropped} records "
            "were checked. Split the file to verify the rest."
        )

    if params.mode == "preflight":
        blocking = counts.get(LIVE_NEWER, 0)
        out["deployable"] = blocking == 0 and not dropped
        if blocking:
            out["message"] = (
                f"DO NOT IMPORT. {blocking} record(s) moved on '{instance}' after "
                "this XML was captured — importing reverts that work. Re-export "
                "with export_record_xml and rebuild the deployment."
            )
        elif counts.get(DIFFERS, 0) or counts.get(MISSING, 0):
            out["message"] = (
                f"{matched} record(s) already match; "
                f"{counts.get(DIFFERS, 0)} differ and {counts.get(MISSING, 0)} are "
                "absent here. Expected against a target that lags — verify against "
                "the SOURCE instance to test the file's freshness."
            )
        else:
            out["message"] = f"All {matched} record(s) match the live server on '{instance}'."
    else:
        not_applied = len(results) - matched
        out["applied"] = matched
        out["not_applied"] = not_applied
        if not_applied:
            out["message"] = (
                f"NOT fully applied on '{instance}': {matched}/{len(results)} "
                "record(s) match this XML. The remainder never landed (or landed "
                "and was changed since). Do not record this deployment as done."
            )
        else:
            out["message"] = f"Confirmed: all {matched} record(s) on '{instance}' match this XML."
        if origin:
            record_applied(
                path,
                instance=instance,
                records_applied=matched,
                records_total=len(results) + dropped,
            )
    return out
