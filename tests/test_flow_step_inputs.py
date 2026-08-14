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
    def test_keeps_the_binding_and_drops_the_metadata(self):
        blob = encode(
            [
                entry("table_name", "incident"),
                entry("conditions", "active=true^priority=1"),
                entry("record", "{{00000000-1111-2222-3333-444444444444.record}}"),
            ]
        )
        inputs, note = _project_step_inputs(blob, [300])
        assert inputs == {
            "table_name": "incident",
            "conditions": "active=true^priority=1",
            # The pill survives verbatim — it is what makes the step traceable.
            "record": "{{00000000-1111-2222-3333-444444444444.record}}",
        }
        assert note is None
        # The parameter block must not survive: it is most of the bytes.
        assert "maxsize" not in json.dumps(inputs)

    def test_unset_inputs_are_omitted_rather_than_listed_as_empty(self):
        blob = encode([entry("set", "yes"), entry("never_configured", "")])
        inputs, _ = _project_step_inputs(blob, [300])
        assert inputs == {"set": "yes"}

    def test_display_value_is_added_only_when_it_says_something_new(self):
        blob = encode(
            [
                entry("assigned_to", "62826bf03710200044e0bfc8bcbe5df1", display="Alice Example"),
                entry("pill", "{{abc.def}}"),  # display == value; adding it doubles cost for 0
            ]
        )
        inputs, _ = _project_step_inputs(blob, [300])
        assert inputs["assigned_to"] == "62826bf03710200044e0bfc8bcbe5df1 (Alice Example)"
        assert inputs["pill"] == "{{abc.def}}"

    def test_a_long_binding_is_cut_and_says_so(self):
        script = "gs.info('x');" * 200
        inputs, _ = _project_step_inputs(encode([entry("script", script)]), [300])
        assert len(inputs["script"]) < len(script)
        assert "chars)" in inputs["script"], "a truncated script must say it was truncated"
        assert inputs["script"].startswith("gs.info('x');")

    def test_non_string_values_survive_as_json(self):
        inputs, _ = _project_step_inputs(encode([entry("flags", {"a": True})]), [300])
        assert json.loads(inputs["flags"]) == {"a": True}


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
        assert second == {}, "the budget was spent by the earlier step"
        assert note == "1 more input(s) not shown"

    def test_could_not_read_is_never_reported_as_binds_nothing(self):
        """The distinction the whole feature rests on.

        A step that binds nothing and a column that would not decode both
        produce an empty dict. Only one of them is an answer, so they must not
        reach the caller looking alike.
        """
        binds_nothing, note_none = _project_step_inputs(encode([]), [300])
        unreadable, note_bad = _project_step_inputs("###not-a-blob###", [300])
        assert binds_nothing == unreadable == {}
        assert note_none is None
        assert note_bad == "unreadable"


class TestSizeDiscipline:
    def test_the_projection_is_a_fraction_of_what_it_decodes(self):
        entries = [entry(f"in{i}", f"value-{i}") for i in range(6)]
        blob = encode(entries)
        inputs, _ = _project_step_inputs(blob, [300])
        decoded_size = len(json.dumps(entries))
        projected_size = len(json.dumps(inputs))
        assert projected_size * 5 < decoded_size, (
            f"projection kept {projected_size} of {decoded_size} chars — the parameter "
            "metadata is supposed to be dropped, not forwarded"
        )
        assert _MAX_INPUT_VALUE_CHARS > 0
