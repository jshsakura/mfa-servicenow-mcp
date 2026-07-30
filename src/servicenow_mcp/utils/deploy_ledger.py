"""Origin ledger for deployment XML: proof that a file came from a live export.

An importable ``<unload>`` file is just text on disk. Anyone can hand-assemble
one in an editor, and a hand-built file is indistinguishable from a live export
by inspection. That is the failure this module exists to make impossible to
miss: an XML set was assembled from stale local copies, nobody could tell it
apart from a real export, and importing it would have reverted two developers'
same-day work on the target.

``export_record_xml`` is remote-only by construction — it reads the live
``sys_update_version`` payload and has no local-file path at all. What it cannot
do is make itself mandatory: the server does not sit between a user and their
text editor, so there is no chokepoint to gate. Instead it ISSUES a certificate
next to every file it writes — the source instance, the export time, and the
live version stamp of every record captured. A file with no certificate is not a
live export, and ``verify_deployment_xml`` refuses it.

Deliberately sidecar-only: the XML bytes are never touched. The importable
format is verified against a real instance (see ``xml_export_tools``) and is not
worth risking for an embedded provenance comment. A lost sidecar therefore fails
SAFE — the file reads as unanchored and gets re-exported, which is the cheap
outcome.

The ``applied`` list is the other half. An export that nobody confirmed landing
is unfinished work, and it surfaces on ``sn_health`` exactly the way unpushed
local edits do (see ``workspace_tools``: automation the LLM must remember to
invoke is not automation). "Recorded as deployed, never imported" is precisely
the state that went unnoticed for a day.

Everything here is disk-only and best-effort: reading or writing the ledger must
never fail an export or a health check.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from servicenow_mcp.utils.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)

SIDECAR_SUFFIX = ".meta.json"
SCHEMA_VERSION = 1
ORIGIN_LIVE_EXPORT = "export_record_xml"

# Work ceilings for the offline health scan. Advisory surface only — the verify
# tool re-checks live, so stopping early can never hide a real problem there.
_MAX_DIRS = 10
_MAX_FILES = 200
_MAX_TRACKED_DIRS = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sidecar_path_for(xml_path: Path) -> Path:
    """``deploy.xml`` -> ``deploy.xml.meta.json``, sitting next to the file.

    Appended (not ``with_suffix``) so the certificate names the exact file it
    certifies: ``a.xml`` and ``a.txt`` can coexist without sharing a sidecar.
    """
    return Path(f"{xml_path}{SIDECAR_SUFFIX}")


def is_sidecar(path: Path) -> bool:
    return path.name.endswith(SIDECAR_SUFFIX)


def write_origin(
    xml_path: Path,
    *,
    source_instance: str,
    source_instance_url: str,
    records: List[Dict[str, Any]],
) -> Optional[Path]:
    """Issue the origin certificate for a freshly exported XML. Never raises."""
    doc = {
        "schema": SCHEMA_VERSION,
        "origin": ORIGIN_LIVE_EXPORT,
        "xml_file": Path(xml_path).name,
        "source_instance": source_instance,
        "source_instance_url": source_instance_url,
        "exported_at": _now(),
        "records": records,
        "applied": [],
    }
    try:
        path = sidecar_path_for(Path(xml_path))
        atomic_write_text(path, json.dumps(doc, indent=1, ensure_ascii=False))
        return path
    except Exception as exc:  # noqa: BLE001 — a ledger write must not fail the export
        logger.warning("deploy_ledger: failed to write origin for %s: %s", xml_path, exc)
        return None


def read_origin(xml_path: Path) -> Optional[Dict[str, Any]]:
    """The certificate for *xml_path*, or None when there is none / it is junk.

    None is the ``unanchored`` verdict's input: absent, unreadable and malformed
    all mean the same thing — this file is not provably a live export.
    """
    path = sidecar_path_for(Path(xml_path))
    try:
        if not path.exists():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("deploy_ledger: unreadable sidecar %s (%s)", path, exc)
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("records"), list):
        return None
    if doc.get("origin") != ORIGIN_LIVE_EXPORT:
        return None
    return doc


def record_applied(
    xml_path: Path,
    *,
    instance: str,
    records_applied: int,
    records_total: int,
) -> bool:
    """Append a landing entry to the certificate. Never raises.

    Only a COMPLETE landing clears the file from the sn_health pending list — a
    partial import is still unfinished work and must keep nagging.
    """
    doc = read_origin(Path(xml_path))
    if doc is None:
        return False
    entry = {
        "instance": instance,
        "at": _now(),
        "records_applied": records_applied,
        "records_total": records_total,
        "complete": records_total > 0 and records_applied == records_total,
    }
    applied = doc.get("applied")
    if not isinstance(applied, list):
        applied = []
    applied.append(entry)
    doc["applied"] = applied[-10:]
    try:
        atomic_write_text(
            sidecar_path_for(Path(xml_path)), json.dumps(doc, indent=1, ensure_ascii=False)
        )
        return True
    except Exception as exc:  # noqa: BLE001 — must not fail the verify call
        logger.warning("deploy_ledger: failed to record landing for %s: %s", xml_path, exc)
        return False


def is_confirmed_applied(doc: Dict[str, Any]) -> bool:
    """True when some instance confirmed a COMPLETE landing of this export."""
    applied = doc.get("applied")
    if not isinstance(applied, list):
        return False
    return any(isinstance(e, dict) and e.get("complete") for e in applied)


# ---------------------------------------------------------------------------
# Where exports live — an auto-registry, so the health scan looks where the
# user really exports instead of only at an assumed ./temp.
# ---------------------------------------------------------------------------


def _state_file() -> Path:
    # Same state dir the auth manager and workspace_roots use.
    return Path.home() / ".mfa_servicenow_mcp" / "xml_dirs.json"


def _read_state() -> Dict[str, str]:
    path = _state_file()
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning("deploy_ledger: unreadable %s (%s) — treating as empty", path, exc)
        return {}


def record_xml_dir(directory: Path) -> None:
    """Remember a directory an export wrote to. Never raises."""
    try:
        key = str(Path(directory).expanduser().resolve())
        state = _read_state()
        state[key] = _now()
        if len(state) > _MAX_TRACKED_DIRS:
            oldest = sorted(state, key=lambda k: state[k])[: len(state) - _MAX_TRACKED_DIRS]
            state = {k: v for k, v in state.items() if k not in oldest}
        path = _state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(state, indent=0))
    except Exception as exc:  # noqa: BLE001 — recording must never fail an export
        logger.warning("deploy_ledger: failed to record dir %s: %s", directory, exc)


def known_xml_dirs() -> List[Path]:
    """Recorded export dirs that still exist, newest first, plus ./temp/*/xml."""
    dirs: List[Path] = []
    seen: set = set()

    def add(path: Path) -> None:
        key = str(path)
        if key not in seen and path.is_dir():
            seen.add(key)
            dirs.append(path)

    try:
        state = _read_state()
        for key in sorted(state, key=lambda k: state[k], reverse=True):
            add(Path(key))
    except Exception as exc:  # noqa: BLE001
        logger.warning("deploy_ledger: failed to list dirs: %s", exc)
    # Fallback for pre-registry exports: the default layout under ./temp.
    try:
        temp = Path.cwd() / "temp"
        if temp.is_dir():
            for child in sorted(temp.iterdir()):
                if child.is_dir():
                    add(child / "xml")
    except OSError:
        pass
    return dirs[:_MAX_DIRS]


def pending_exports() -> Dict[str, Any]:
    """Offline summary of exports nobody confirmed landing. Never raises.

    Empty dict when there is nothing to say — the caller (sn_health) stays
    silent rather than adding noise to every health check.
    """
    try:
        unconfirmed: List[tuple] = []
        scanned = 0
        for directory in known_xml_dirs():
            if scanned >= _MAX_FILES:
                break
            try:
                entries = sorted(directory.iterdir())
            except OSError:
                continue
            for entry in entries:
                if scanned >= _MAX_FILES:
                    break
                if not entry.is_file() or not is_sidecar(entry):
                    continue
                scanned += 1
                xml_file = Path(str(entry)[: -len(SIDECAR_SUFFIX)])
                if not xml_file.exists():
                    continue
                doc = read_origin(xml_file)
                if doc is None or is_confirmed_applied(doc):
                    continue
                unconfirmed.append((str(doc.get("exported_at") or ""), xml_file))
        if not unconfirmed:
            return {}
        unconfirmed.sort(key=lambda item: item[0])
        oldest_at, oldest_path = unconfirmed[0]
        out: Dict[str, Any] = {"unconfirmed_exports": len(unconfirmed)}
        out["oldest"] = f"{oldest_path.name} (exported {oldest_at or 'unknown'})"
        out["next"] = (
            f"Nobody confirmed these landed. verify_deployment_xml(xml_path="
            f"'{oldest_path}', mode='postflight') while the TARGET instance is "
            "active — it reports applied vs not_applied per record."
        )
        return out
    except Exception as exc:  # noqa: BLE001 — must never break a health check
        logger.warning("deploy_ledger: pending scan skipped: %s", exc)
        return {}
