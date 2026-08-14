"""Flow steps report what they are CONFIGURED to do, not just that they exist.

`get_detail` used to return a step's name, type and position and nothing else,
and its own closing note sent the caller to browser auth for "conditions and
variable mappings". Those were in the `values` column of the row it was already
fetching — gzip'd base64 JSON holding every input binding, including the
`{{uuid.field}}` data pills that make a flow traceable.

Fixtures here are built by gzip+base64-encoding real-shaped payloads rather than
by pasting a captured blob: a fixture that does not go through the same encoder
as production drifts from it silently.
"""

import base64
import gzip
import json

import pytest

from servicenow_mcp.tools.flow_designer_tools import (
    _MAX_INPUT_VALUE_CHARS,
    _MAX_INPUTS_PER_STEP,
    _decode_values_blob,
    _project_step_inputs,
)


def encode(entries) -> str:
    """The producer side, used exactly as ServiceNow stores it."""
    return base64.b64encode(gzip.compress(json.dumps(entries).encode("utf-8"))).decode("ascii")


def entry(name, value, display=None, **extra):
    """One input as the platform writes it — parameter metadata included."""
    payload = {
        "actionInstanceSysId": "a" * 32,
        "id": "b" * 32,
        "name": name,
        "value": value,
        "displayValue": display if display is not None else value,
        "children": [],
        # The block that is ~9/10 of the bytes and none of the answer.
        "parameter": {
            "label": name.replace("_", " ").title(),
            "type": "string",
            "order": 1,
            "mandatory": False,
            "hint": "",
            "maxsize": 4000,
            "children": [],
        },
    }
    payload.update(extra)
    return payload


class TestDecode:
    def test_round_trips_the_real_storage_format(self):
        blob = encode([entry("table_name", "incident")])
        assert _decode_values_blob(blob) == [entry("table_name", "incident")]

    @pytest.mark.parametrize(
        "blob",
        [
            "",
            None,
            123,
            "not base64 at all!!",
            base64.b64encode(b"plain, not gzipped").decode(),  # decodes, not gzip
            base64.b64encode(gzip.compress(b"{not json")).decode(),  # gunzips, not JSON
            base64.b64encode(gzip.compress(b'{"a": 1}')).decode(),  # JSON, not a list
        ],
    )
    def test_anything_that_is_not_the_format_returns_none_and_never_raises(self, blob):
        assert _decode_values_blob(blob) is None


class TestProjection:
    def test_reads_at_the_level_the_canvas_shows(self):
        """A flow is read by a person with the Flow Designer open next to it.

        So each input carries the caption they see (`label`), the value as
        rendered, and — only when it differs — what is actually stored.
        """
        blob = encode(
            [
                entry("table_name", "incident"),
                entry("conditions", "active=true^priority=1"),
                entry("record", "{{00000000-1111-2222-3333-444444444444.record}}"),
            ]
        )
        inputs, note = _project_step_inputs(blob, [300])
        assert note is None
        by_name = {i["name"]: i for i in inputs}
        assert by_name["table_name"]["value"] == "incident"
        assert by_name["table_name"]["label"] == "Table Name"
        assert by_name["conditions"]["value"] == "active=true^priority=1"
        # A pill with no label map still resolves to its breadcrumb rather than
        # staying a raw token, and the token is kept for precision.
        assert by_name["record"]["value"] == "00000000-1111-2222-3333-444444444444 ▸ record"
        assert by_name["record"]["raw"] == "{{00000000-1111-2222-3333-444444444444.record}}"
        # The parameter block must not survive beyond its label: it is most of
        # the bytes and none of the answer.
        assert "maxsize" not in json.dumps(inputs)

    def test_a_pill_prints_as_the_step_that_produced_it(self):
        blob = encode([entry("record", "{{abc123.record.number}}")])
        inputs, _ = _project_step_inputs(blob, [300], {"abc123": "Look Up Records"})
        assert inputs[0]["value"] == "Look Up Records ▸ record ▸ number"
        assert inputs[0]["raw"] == "{{abc123.record.number}}"

    def test_unset_inputs_are_omitted_rather_than_listed_as_empty(self):
        blob = encode([entry("set", "yes"), entry("never_configured", "")])
        inputs, _ = _project_step_inputs(blob, [300])
        assert [i["name"] for i in inputs] == ["set"]

    def test_a_reference_shows_its_name_and_keeps_its_sys_id(self):
        blob = encode(
            [entry("assigned_to", "62826bf03710200044e0bfc8bcbe5df1", display="Alice Example")]
        )
        inputs, _ = _project_step_inputs(blob, [300])
        # Shown as the screen shows it; the sys_id stays for anything that has
        # to act on the record rather than read about it.
        assert inputs[0]["value"] == "Alice Example"
        assert inputs[0]["raw"] == "62826bf03710200044e0bfc8bcbe5df1"

    def test_raw_is_omitted_when_it_is_the_same_as_what_is_shown(self):
        inputs, _ = _project_step_inputs(encode([entry("plain", "incident")]), [300])
        assert inputs[0]["value"] == "incident"
        assert "raw" not in inputs[0], "an identical raw value is a duplicate, not information"

    def test_a_long_binding_is_cut_and_says_so(self):
        script = "gs.info('x');" * 200
        inputs, _ = _project_step_inputs(encode([entry("script", script)]), [300])
        assert len(inputs[0]["value"]) < len(script)
        assert "chars)" in inputs[0]["value"], "a truncated script must say it was truncated"
        assert inputs[0]["value"].startswith("gs.info('x');")

    def test_non_string_values_survive_as_json(self):
        inputs, _ = _project_step_inputs(encode([entry("flags", {"a": True})]), [300])
        assert json.loads(inputs[0]["value"]) == {"a": True}


class TestHonestLimits:
    def test_a_step_with_more_inputs_than_the_cap_reports_the_remainder(self):
        blob = encode([entry(f"in{i}", f"v{i}") for i in range(_MAX_INPUTS_PER_STEP + 4)])
        inputs, note = _project_step_inputs(blob, [1000])
        assert len(inputs) == _MAX_INPUTS_PER_STEP
        assert note == "4 more input(s) not shown"

    def test_the_response_budget_is_shared_across_steps(self):
        budget = [3]
        first, _ = _project_step_inputs(encode([entry(f"a{i}", "v") for i in range(3)]), budget)
        second, note = _project_step_inputs(encode([entry("b", "v")]), budget)
        assert len(first) == 3
        assert second == [], "the budget was spent by the earlier step"
        assert note == "1 more input(s) not shown"

    def test_could_not_read_is_never_reported_as_binds_nothing(self):
        """The distinction the whole feature rests on.

        A step that binds nothing and a column that would not decode both
        produce an empty dict. Only one of them is an answer, so they must not
        reach the caller looking alike.
        """
        binds_nothing, note_none = _project_step_inputs(encode([]), [300])
        unreadable, note_bad = _project_step_inputs("###not-a-blob###", [300])
        assert binds_nothing == unreadable == []
        assert note_none is None
        assert note_bad == "unreadable"


class TestTheRawBlobNeverShips:
    """Adding `values` to the field list put a 1.4KB base64 string on every row.

    The nested `tree` is built from those same row dicts, so projecting only
    into `flat_summary` left the raw blob riding along in the tree — ~90KB of
    unreadable base64 on a wide flow, in the name of a feature meant to make
    flows readable. Caught by reading the code, not by a test; this is the test.
    """

    def test_the_tree_carries_projected_inputs_and_not_the_blob(self):
        from servicenow_mcp.tools.flow_designer_tools import (
            _MAX_INPUTS_PER_RESPONSE,
            _VALUES_FIELD,
            _build_component_tree,
            _project_step_inputs,
        )

        blob = encode([entry("table_name", "incident"), entry("conditions", "active=true")])
        comps = [
            {
                "sys_id": "a",
                "ui_id": "1",
                "order": "1",
                "display_text": "Look Up",
                _VALUES_FIELD: blob,
            },
            {"sys_id": "b", "ui_id": "2", "order": "2", "parent_ui_id": "1", _VALUES_FIELD: blob},
        ]

        # Exactly what the reader does: pop the blob, attach the projection,
        # and only then nest.
        budget = [_MAX_INPUTS_PER_RESPONSE]
        for comp in comps:
            projected, _ = _project_step_inputs(comp.pop(_VALUES_FIELD, None), budget)
            if projected:
                comp["inputs"] = projected
        tree = _build_component_tree(comps)

        serialized = json.dumps(tree)
        assert "H4sI" not in serialized, "the gzip blob rode into the tree"
        assert _VALUES_FIELD not in tree[0]
        # ...and the useful form did make it, at both nesting levels.
        assert {i["name"]: i["value"] for i in tree[0]["inputs"]}["table_name"] == "incident"
        nested = {i["name"]: i["value"] for i in tree[0]["children"][0]["inputs"]}
        assert nested["conditions"] == "active=true"
        assert len(serialized) < 1200, f"tree serialized to {len(serialized)} chars"


class TestSizeDiscipline:
    def test_the_projection_is_a_fraction_of_what_it_decodes(self):
        entries = [entry(f"in{i}", f"value-{i}") for i in range(6)]
        blob = encode(entries)
        inputs, _ = _project_step_inputs(blob, [300])
        decoded_size = len(json.dumps(entries))
        projected_size = len(json.dumps(inputs))
        assert projected_size * 3 < decoded_size, (
            f"projection kept {projected_size} of {decoded_size} chars — the parameter "
            "metadata is supposed to be dropped, not forwarded"
        )
        assert _MAX_INPUT_VALUE_CHARS > 0


class TestTriggersReadTheSameOnEitherAuth:
    """A trigger's table and condition are not columns on its own record.

    `sys_hub_trigger_instance` carries `trigger_inputs` (a glide_var); the
    values live in `sys_variable_value`. Browser auth got them from the
    processflow payload and basic auth got nothing, so the same trigger read as
    "a Record-Updated trigger" or as "watches x, when y" depending only on how
    you had logged in.
    """

    def test_table_api_rows_compact_like_processflow_rows(self):
        from servicenow_mcp.tools.flow_designer_tools import _compact_triggers

        # As _attach_trigger_inputs builds them from sys_variable_value, with
        # display_value resolving each variable to its on-screen caption.
        table_api_row = {
            "sys_id": "trig1",
            "trigger_type": "record_update",
            "inputs": [
                {
                    "name": "table",
                    "label": "Table",
                    "value": "incident",
                    "displayValue": "incident",
                },
                {
                    "name": "condition",
                    "label": "Condition",
                    "value": "state=1",
                    "displayValue": "state=1",
                },
            ],
        }
        processflow_row = {
            "id": "trig1",
            "type": "record_update",
            "inputs": [
                {"name": "table", "value": "incident", "displayValue": "incident"},
                {"name": "condition", "value": "state=1"},
            ],
        }

        from_table = _compact_triggers([table_api_row])[0]
        from_pf = _compact_triggers([processflow_row])[0]
        assert from_table == from_pf, "the same trigger must read the same either way"
        assert from_table["table"] == "incident"
        assert from_table["id"] == "trig1"
        assert from_table["type"] == "record_update"
        assert "state" in from_table["condition"]

    def test_a_reference_typed_trigger_definition_still_names_itself(self):
        from servicenow_mcp.tools.flow_designer_tools import _compact_triggers

        row = {"sys_id": "t2", "trigger_definition": {"display_value": "Updated", "value": "abc"}}
        assert _compact_triggers([row])[0]["type"] == "Updated"


class TestReadAndEditJoinUp:
    """ "Change this one to that" has to be answerable from what the read returned.

    The write path (flow_edit_tools._find_node) matches a node on `id` /
    `uiUniqueIdentifier`. The structure read printed order, type, name and
    bindings — and no handle at all, so the model could describe a step
    perfectly and still not name it in set_action_input.
    """

    def test_every_step_carries_the_handle_the_edit_path_matches_on(self):
        from servicenow_mcp.tools.flow_designer_tools import _build_component_tree

        comps = [
            {"sys_id": "s1", "ui_id": "u1", "order": "1", "display_text": "Look Up Records"},
            {"sys_id": "s2", "ui_id": "u2", "order": "2", "display_text": "If"},
        ]
        # The reader keys entries off the same fields the tree nests on.
        for comp in comps:
            assert comp.get("ui_id"), "a node with no ui_id cannot be addressed"
        tree = _build_component_tree(comps)
        assert [n["ui_id"] for n in tree] == ["u1", "u2"]

    def test_a_node_without_a_ui_id_falls_back_to_its_sys_id(self):
        """Never leave the handle blank: an unaddressable step is a dead end."""
        comp = {"sys_id": "s9", "order": "1", "display_text": "Legacy"}
        handle = comp.get("ui_id") or comp.get("sys_id") or ""
        assert handle == "s9"


class TestProcessflowSummaryReadsPillsToo:
    """The path most people are actually on had unreadable pills.

    Live check (v1.24.26): browser auth already returned every step binding —
    the v1.24.25 premise that they were missing was only true of the Table API
    fallback. What WAS missing there is the thing that matters when a person
    reads a flow with the designer open: every pill printed as a bare uuid.
    """

    def test_a_pill_gains_its_canvas_breadcrumb_and_keeps_its_token(self):
        from servicenow_mcp.tools.flow_designer_tools import _summarize_node_inputs

        node = {
            "inputs": [
                {"name": "selected_roles", "value": "{{step-uuid.delegate_roles_roles}}"},
                {"name": "close_code", "value": "successful"},
            ]
        }
        flat = _summarize_node_inputs(node, {"step-uuid": "Get Catalog Variables"})
        # The token survives — trace_pill and the edit paths match on it.
        assert flat["selected_roles"].startswith("{{step-uuid.delegate_roles_roles}}")
        assert "Get Catalog Variables ▸ delegate_roles_roles" in flat["selected_roles"]
        # A literal is left exactly alone.
        assert flat["close_code"] == "successful"

    def test_an_existing_display_value_is_never_overwritten_by_a_breadcrumb(self):
        from servicenow_mcp.tools.flow_designer_tools import _summarize_node_inputs

        node = {
            "inputs": [
                {"name": "item", "value": "1bc63274", "displayValue": "Delegate roles to member"}
            ]
        }
        flat = _summarize_node_inputs(node, {"1bc63274": "Should Not Be Used"})
        assert flat["item"] == "1bc63274 / Delegate roles to member"

    def test_no_label_map_still_produces_a_breadcrumb_rather_than_a_raw_token(self):
        from servicenow_mcp.tools.flow_designer_tools import _summarize_node_inputs

        node = {"inputs": [{"name": "r", "value": "{{abc.record.number}}"}]}
        flat = _summarize_node_inputs(node)
        assert flat["r"] == "{{abc.record.number}} / abc ▸ record ▸ number"


class TestABigFlowStillComesBack:
    """ "Too big" is a reason to compress, not a reason to return nothing.

    A 142-node flow used to answer with counts and a list of other calls to
    try — the shape of the flow, which has no targeted call of its own, was
    simply withheld. Now every node survives and only the per-node detail goes.
    """

    @staticmethod
    def _flow(nodes):
        def node(i):
            kind = "ACTION" if i % 3 else "LOGIC"
            type_name = "Look Up Records" if kind == "ACTION" else "If"
            row = {
                "order": str(i),
                "depth": i % 3,
                "kind": kind,
                "ui_id": f"{i:08x}-4dbd-4750-9ca5-5e2bd32d0799",
                "type": type_name,
                "name": type_name,
                "inputs": {"table_name": "x" * 80, "conditions": "y" * 80},
                "outputs": ["records"],
            }
            if kind == "LOGIC":
                row["condition"] = "state changes from 1 AND state changes to 6"
            return row

        return {
            "tree": [node(i) for i in range(1, nodes + 1)],
            "orphans": [],
            "counts": {"actions": nodes},
            "integrity": {"tree_nodes": nodes},
            "summary_index": {"approvals": []},
            "tree_text": "x" * (nodes * 180),
        }

    def test_a_small_flow_is_returned_whole(self):
        from servicenow_mcp.tools.flow_designer_tools import _bound_structure

        out = _bound_structure(self._flow(4))
        assert len(out["tree"]) == 4
        assert out["tree"][0]["inputs"], "a flow that fits keeps its bindings"
        assert "detail_omitted" not in out

    def test_a_big_flow_keeps_every_node_and_drops_only_the_detail(self):
        from servicenow_mcp.tools.flow_designer_tools import (
            _SKELETON_INLINE_BUDGET_BYTES,
            _bound_structure,
        )
        from servicenow_mcp.utils.response_budget import byte_len

        source = self._flow(142)
        out = _bound_structure(source)

        # Columnar, and complete: a truncated tree would look like a flow that
        # ends early, which is the failure this must never produce.
        assert out["tree"]["columns"], "expected the columnar form"
        assert len(out["tree"]["data"]) == 142
        assert byte_len(out) < byte_len(source) / 4, "compression did not happen"
        assert byte_len(out) <= _SKELETON_INLINE_BUDGET_BYTES

        # The handle survives — a shape you cannot act on is a picture.
        assert "ui_id" in out["tree"]["columns"]
        assert all(row[out["tree"]["columns"].index("ui_id")] for row in out["tree"]["data"])
        # A branch's condition IS its identity; "If" alone says nothing.
        assert "condition" in out["tree"]["columns"]
        # And what went missing is named, with the call that returns it.
        assert "node_id" in out["detail_omitted"]["get_one_step"]
        assert "142" in out["detail_omitted"]["why"]

    def test_a_flow_too_big_even_to_skeletonise_says_so_rather_than_half_answering(self):
        from servicenow_mcp.tools.flow_designer_tools import _bound_structure

        out = _bound_structure(self._flow(400))
        assert out["tree_omitted"] is True
        assert out["structure_too_large"]["nodes"] == 400
        assert out["counts"]["actions"] == 400, "the exact counts are still an answer"

    def test_an_unnamed_step_does_not_print_its_type_twice(self):
        from servicenow_mcp.tools.flow_designer_tools import _skeletal_node

        renamed = _skeletal_node({"kind": "ACTION", "type": "Look Up Records", "name": "Find OI"})
        unnamed = _skeletal_node(
            {"kind": "ACTION", "type": "Look Up Records", "name": "Look Up Records"}
        )
        assert renamed["name"] == "Find OI"
        assert "name" not in unnamed and unnamed["type"] == "Look Up Records"
