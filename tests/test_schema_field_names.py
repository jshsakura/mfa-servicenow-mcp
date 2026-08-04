"""Every field name the package writes or filters on must exist on its table.

This is the one class of defect a mock cannot see. ServiceNow accepts what it
does not understand: an unknown field in `sysparm_fields` is omitted from the
response, an unknown condition in an encoded query is DROPPED (so the read comes
back with the whole table), and an unknown key in a write body is ignored and
answered 200. A fixture, meanwhile, returns whatever key it was written with —
so a full green suite proves nothing about a name.

Found this way, on a live instance, in one afternoon:

  sys_hub_flow_snapshot.master_flow   filter -> 808 rows, i.e. unfiltered; the
                                      flow-structure fallback reported an
                                      unrelated flow's steps as yours
  wf_activity.order                   write  -> ignored; "Activities reordered"
                                      for a change that never happened
  wf_workflow.active                  write  -> ignored; activation lives on
                                      wf_workflow_version.published
  wf_activity.description             write  -> ignored; the column is `notes`
  sp_page.description                 write  -> ignored; `short_description`
  item_option_new.max_length/min/max  write  -> ignored; `attributes`/`scale_*`
  *_instance_v2.name/nesting_parent   read   -> blank labels, flat tree

`tests/fixtures/live_schema.json` is a recorded column set from a real instance
(`python scripts/audit_query_fields.py --record`). It is a SNAPSHOT, not the
truth — it says what one instance had on one day — so this test is deliberately
one-directional: it fails a name that exists NOWHERE in the recording, and never
demands that a name be present. Refreshing the file is a deliberate act with a
diff to read.

`u_*` / `x_*` are skipped on both sides: they are instance customisations, they
are not recorded (a customer's schema does not belong in a public repo), and no
snapshot could validate them anyway.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO / "tests" / "fixtures" / "live_schema.json"
AUDIT = REPO / "scripts" / "audit_query_fields.py"

CUSTOMISATION = re.compile(r"^(u_|x_)")


# Dot-walked references are resolved by the server against a different table, so
# the local column set has nothing to say about them.
def _checkable(fields):
    return {f for f in fields if f and "." not in f and not CUSTOMISATION.match(f)}


def _audit_module():
    spec = importlib.util.spec_from_file_location("audit_query_fields", AUDIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def schema():
    assert SNAPSHOT.is_file(), (
        f"{SNAPSHOT.relative_to(REPO)} is missing. Regenerate it against a live "
        "instance: python scripts/audit_query_fields.py --record"
    )
    return json.loads(SNAPSHOT.read_text())


@pytest.fixture(scope="module")
def audit():
    return _audit_module()


def test_the_snapshot_carries_no_instance_customisations(schema):
    """A customer's own columns must never reach this repository."""
    leaked = {
        f"{table}.{column}"
        for table, columns in schema.items()
        for column in columns
        if CUSTOMISATION.match(column)
    }
    assert not leaked, f"customisation columns in the snapshot: {sorted(leaked)[:10]}"


def test_no_query_filters_on_a_field_that_exists_nowhere(schema, audit):
    """The 808-row failure. A dropped condition returns everything."""
    offenders = []
    for table, used in audit.collect().items():
        columns = schema.get(table)
        if not columns:
            continue  # not recorded: unchecked, which is not the same as passed
        checkable = _checkable(used["query"])
        # A dropped condition only unfilters the read when nothing else
        # constrains it. Measured: `parent_flow=F` -> 21 rows,
        # `master_flow=F` (no such column) -> 808, and the two OR'd together ->
        # 21. So naming a field two ways on purpose, to survive a rename between
        # releases, is careful code rather than a defect — and flagging it would
        # make this test wrong exactly where the code is right.
        if any(f in columns for f in checkable):
            continue
        for field in sorted(checkable):
            if field not in columns:
                offenders.append(f"{table}: filters on '{field}' with nothing else to filter on")
    assert not offenders, "\n".join(offenders)


# There is deliberately NO allowlist here.
#
# One was written, with six entries and a reason beside each. Every reason was
# wrong: probed one at a time on a live instance, all six turned out to be plain
# mistakes with a correct column sitting on the SAME table — `kb_category.parent`
# (really parent_id + parent_table), `kb_knowledge_base.workflow_publish` (really
# kb_publish_flow), `sys_update_set.developer` (no such thing). The list was not
# recording version differences; it was recording six bugs and calling them
# breadth, which is precisely how a check stops being a check.
#
# The probe that settles it costs one query and cannot be argued with: filter the
# table on `<field>ISNOTEMPTY` and on `<field>ISEMPTY`. A real column splits the
# rows. A field that does not exist has its condition dropped, so BOTH return
# every row. Run that before deciding a name is a variant rather than a defect.


def test_no_write_names_a_field_that_does_not_exist(schema, audit):
    """The worst failure mode: accepted, ignored, and reported as done.

    Absence from the snapshot is not proof of a defect on its own — this tool
    runs against many instances and releases. It IS proof that the field cannot
    be relied on, so it has to be resolved rather than tolerated: probe it (see
    the note above) and either fix the name or record why the difference is real.
    """
    unexplained = []
    for table, used in audit.collect_writes().items():
        columns = schema.get(table)
        if not columns:
            continue  # not recorded: unchecked, which is not the same as passed
        for field in sorted(_checkable(used["fields"])):
            if field in columns:
                continue
            unexplained.append(
                f"{table}.{field} written by {', '.join(sorted(used['where']))} — "
                "not on the recorded instance. Probe it: a filter on "
                f"'{field}ISNOTEMPTY' and on '{field}ISEMPTY' both returning every row "
                "means the column does not exist and the write is being discarded."
            )
    assert not unexplained, "\n".join(unexplained)


def test_the_extractor_still_finds_the_known_call_sites(audit):
    """A silent regression in the parser would make both checks vacuously pass.

    The two assertions above only fail on what they manage to extract, so an
    extractor that quietly stopped seeing anything would report a clean tree —
    the exact shape of defect this file exists to catch.
    """
    reads = audit.collect()
    writes = audit.collect_writes()

    assert len(reads) > 30, f"read extraction collapsed to {len(reads)} tables"
    assert len(writes) > 5, f"write extraction collapsed to {len(writes)} tables"
    assert "sys_script" in reads
    assert "sys_hub_flow_snapshot" in reads
    assert _checkable(reads["sys_hub_flow_snapshot"]["query"]) >= {"parent_flow", "sys_id"}


@pytest.mark.parametrize(
    "table,field",
    [
        ("sys_hub_flow_snapshot", "master_flow"),  # filter -> whole table
        ("wf_activity", "order"),  # write -> ignored, "reordered"
        ("wf_workflow", "active"),  # write -> ignored, "activated"
        ("wf_activity", "description"),  # write -> ignored, column is `notes`
        ("sp_page", "description"),  # write -> ignored, `short_description`
        ("item_option_new", "max_length"),  # write -> ignored, goes in `attributes`
    ],
)
def test_the_columns_that_caused_todays_bugs_really_are_absent(schema, table, field):
    """Pins the measurement itself, so the snapshot cannot drift into agreeing
    with the code by accident."""
    columns = schema.get(table)
    assert columns, f"{table} is not in the snapshot"
    assert field not in columns
