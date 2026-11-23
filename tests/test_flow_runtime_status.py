"""_flow_runtime_status: the direct publish answer, so a caller never has to read
the sys_hub_flow snapshot columns to tell "draft status" from "live".

The rows below mirror a PDI measurement (2026-11-23): saving an edit without
publishing turns the design flow's ``status`` to ``draft`` and moves NEITHER
``master_snapshot`` nor ``latest_snapshot``. So ``status`` is the signal, and
``latest != master`` is not."""

from unittest.mock import MagicMock, patch

from servicenow_mcp.tools import sn_api
from servicenow_mcp.tools.flow_designer_tools import (
    _draft_changes,
    _flow_runtime_status,
    get_flow_details,
)

FLOW = "aaaa1111bbbb2222cccc3333dddd4444"
MASTER = "aaaa1111bbbb2222cccc3333dddd5555"
LATEST = "aaaa1111bbbb2222cccc3333dddd6666"
OTHER_FLOW = "aaaa1111bbbb2222cccc3333dddd7777"


def _flow_row(active, status, master, latest=None):
    return [
        {
            "sys_id": FLOW,
            "active": active,
            "status": status,
            "master_snapshot": master,
            "latest_snapshot": master if latest is None else latest,
        }
    ]


def _answer(by_table):
    """sn_query_page stand-in keyed by table; a value may be an exception."""

    def fake(config, auth_manager, *, table, **kwargs):
        value = by_table.get(table, [])
        if isinstance(value, Exception):
            raise value
        return (value, None)

    return fake


def _run(by_table, flow_id=FLOW):
    with patch(
        "servicenow_mcp.tools.flow_designer_tools.sn_query_page", side_effect=_answer(by_table)
    ):
        return _flow_runtime_status(MagicMock(), MagicMock(), flow_id)


def test_published_is_current():
    out = _run({"sys_hub_flow": _flow_row("true", "published", MASTER)})
    assert out["live"] is True
    assert out["published_is_current"] is True
    assert out["has_unpublished_edits"] is False
    assert out["determined"] is True


def test_saved_unpublished_edit_is_reported_even_though_snapshots_did_not_move():
    # The measured shape: status draft, master == latest. The old check read
    # this as "the published version IS the latest".
    out = _run({"sys_hub_flow": _flow_row("true", "draft", MASTER)})
    assert out["has_unpublished_edits"] is True
    assert out["published_is_current"] is False
    assert out["determined"] is True
    assert "DRAFT" in out["note"] and MASTER in out["note"]


def test_latest_differing_from_master_alone_is_not_a_draft():
    # The askme case: published, latest_snapshot names an id no row answers.
    out = _run({"sys_hub_flow": _flow_row("true", "published", MASTER, LATEST)})
    assert out["has_unpublished_edits"] is False
    assert out["published_is_current"] is True
    assert out["latest_snapshot"] == LATEST


def test_unknown_status_is_undetermined():
    out = _run({"sys_hub_flow": _flow_row("true", "", MASTER)})
    assert out["has_unpublished_edits"] is None
    assert out["determined"] is False
    assert "NOT determined" in out["note"]


def test_not_live_when_inactive():
    out = _run({"sys_hub_flow": _flow_row("false", "published", MASTER)})
    assert out["live"] is False
    assert out["published_is_current"] is False
    assert "NOT LIVE" in out["note"]


def test_snapshot_sys_id_is_named_with_its_flow():
    # processflow serves a snapshot id too; the runtime must not come back empty.
    out = _run(
        {
            "sys_hub_flow": [],
            "sys_hub_flow_snapshot": [
                {"sys_id": MASTER, "parent_flow": FLOW, "status": "published"}
            ],
        },
        flow_id=MASTER,
    )
    assert out["is_snapshot"] is True
    assert out["flow_sys_id"] == FLOW
    assert FLOW in out["note"]


def test_missing_flow_is_undetermined_not_empty():
    out = _run({"sys_hub_flow": [], "sys_hub_flow_snapshot": []}, flow_id=OTHER_FLOW)
    assert out["determined"] is False
    assert "unknown" in out["note"]


def test_lookup_failure_is_advisory_and_says_so():
    # Never break get_detail on a runtime-status lookup error — and never go quiet.
    out = _run({"sys_hub_flow": RuntimeError("boom")})
    assert out["determined"] is False
    assert "boom" in out["note"]


def test_publish_state_is_never_served_from_the_query_cache():
    # A Workflow Studio save does not pass through this server, so a cached row
    # from before the save would still say "published".
    key = sn_api._cache_key(
        "https://x",
        "sys_hub_flow",
        "q",
        "f",
        1,
        0,
        display_value=False,
        no_count=False,
        orderby=None,
    )
    sn_api._cache_put(key, (["stale"], 1))
    _run({"sys_hub_flow": _flow_row("true", "draft", MASTER)})
    assert sn_api._cache_get(key) is None


# --- what the draft changed -------------------------------------------------


def _node(ui_id, order, message):
    return {
        "order": order,
        "ui_id": ui_id,
        "kind": "ACTION",
        "type": "Log",
        "inputs": {"log_message": message},
    }


def test_draft_changes_lists_added_removed_and_changed_by_ui_id():
    published = [_node("u1", "1", "one"), _node("u2", "2", "two")]
    draft = [_node("u1", "1", "one EDITED"), _node("u3", "2", "three")]
    out = _draft_changes(draft, published)
    assert out["identical"] is False
    assert out["added"] == ["[2] Log"]
    assert out["removed"] == ["[2] Log"]
    assert out["changed"] == [{"step": "[1] Log", "fields": ["inputs"]}]


def test_draft_changes_insertion_does_not_mark_later_steps_changed_except_order():
    published = [_node("u1", "1", "one"), _node("u2", "2", "two")]
    draft = [_node("u0", "1", "new"), _node("u1", "2", "one"), _node("u2", "3", "two")]
    out = _draft_changes(draft, published)
    assert out["added"] == ["[1] Log"]
    assert out["removed"] == []
    assert all(c["fields"] == ["order"] for c in out["changed"])


def test_draft_changes_identical_trees():
    tree = [_node("u1", "1", "one")]
    assert _draft_changes(tree, list(tree))["identical"] is True


def _pf_flow(nodes):
    """Minimal processflow payload: one Log action per (ui_id, order, message)."""
    return {
        "id": FLOW,
        "name": "Probe",
        "status": "draft",
        "active": True,
        "actionInstances": [
            {
                "id": f"sys-{ui}",
                "uiUniqueIdentifier": ui,
                "order": order,
                "name": "Log",
                "actionType": {"name": "Log", "internal_name": "log"},
                "inputs": [{"name": "log_message", "value": msg, "displayValue": msg}],
            }
            for ui, order, msg in nodes
        ],
        "flowLogicInstances": [],
        "subFlowInstances": [],
    }


def test_get_detail_on_a_draft_reports_what_the_draft_changed():
    from servicenow_mcp.tools.flow_designer_tools import GetFlowDetailsParams
    from servicenow_mcp.utils.config import AuthType

    config = MagicMock()
    config.auth.type = AuthType.BROWSER
    draft = _pf_flow([("u1", "1", "one"), ("u2", "2", "two DRAFT")])
    published = _pf_flow([("u1", "1", "one")])

    def processflow(cfg, am, flow_id):
        return {"result": draft if flow_id == FLOW else published}

    runtime = {
        "live": True,
        "has_unpublished_edits": True,
        "master_snapshot": MASTER,
        "determined": True,
    }
    base = "servicenow_mcp.tools.flow_designer_tools."
    with (
        patch(base + "_try_processflow_api", side_effect=processflow),
        patch(base + "_flow_runtime_status", return_value=dict(runtime)),
        patch(base + "_attach_stages_and_signature", side_effect=lambda s, *a: s),
        patch(base + "_make_choice_resolver", return_value=None),
    ):
        out = get_flow_details(
            config, MagicMock(), GetFlowDetailsParams(flow_id=FLOW, include_structure=True)
        )
    changes = out["runtime"]["draft_changes"]
    assert changes["determined"] is True
    assert changes["compared_with"] == MASTER
    assert len(changes["added"]) == 1 and changes["removed"] == []


# --- who saved the draft ------------------------------------------------------


def _version(kind, on, by):
    return {"type": kind, "sys_created_on": on, "sys_created_by": by}


def test_draft_names_who_saved_since_the_last_publish():
    out = _run(
        {
            "sys_hub_flow": _flow_row("true", "draft", MASTER),
            # Newest first, as the read orders it.
            "sys_hub_flow_version": [
                _version("Autosave", "2026-01-02 10:05:00", "bob"),
                _version("Autosave", "2026-01-02 10:01:00", "alice"),
                _version("Activate/Publish", "2026-01-02 09:00:00", "alice"),
                _version("Autosave", "2026-01-01 09:00:00", "other.dev"),
            ],
        }
    )
    edits = out["edits_since_publish"]
    assert edits["checked"] is True and edits["complete"] is True
    assert edits["saves"] == 2
    assert edits["by"] == ["alice", "bob"]  # other.dev saved BEFORE the publish
    assert edits["last_saved_on"] == "2026-01-02 10:05:00"
    assert edits["last_published_on"] == "2026-01-02 09:00:00"


def test_a_full_page_of_saves_without_a_publish_is_not_complete():
    from servicenow_mcp.tools.flow_designer_tools import _VERSION_PAGE

    page = [_version("Autosave", "2026-01-02 10:00:00", "bob")] * _VERSION_PAGE
    out = _run({"sys_hub_flow": _flow_row("true", "draft", MASTER), "sys_hub_flow_version": page})
    edits = out["edits_since_publish"]
    assert edits["complete"] is False
    assert "may be missing" in edits["note"]


def test_unreadable_version_history_is_not_checked():
    out = _run(
        {
            "sys_hub_flow": _flow_row("true", "draft", MASTER),
            "sys_hub_flow_version": RuntimeError("403 Forbidden"),
        }
    )
    assert out["has_unpublished_edits"] is True  # the status still decides
    assert out["edits_since_publish"]["checked"] is False
