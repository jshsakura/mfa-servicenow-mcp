"""A dead session must fail with what happened, not with a Python type name."""

from unittest.mock import MagicMock

import pytest

from servicenow_mcp.utils.http_result import json_object, json_result


def _resp(payload=None, *, raises=False, text=""):
    r = MagicMock()
    if raises:
        r.json.side_effect = ValueError("Expecting value: line 1 column 1")
    else:
        r.json.return_value = payload
    r.text = text
    return r


class TestJsonObject:
    def test_a_dict_body_passes_through(self):
        assert json_object(_resp({"result": {"a": 1}})) == {"result": {"a": 1}}

    def test_a_string_body_is_named_not_crashed(self):
        """The reported failure: `'str' object has no attribute 'get'`, twice, on a
        push that never reached the server. It names a Python type, not the thing
        that happened — the session had stopped being usable."""
        with pytest.raises(ValueError) as exc:
            json_object(_resp("<html>login</html>"), "fetch sp_widget/wid-1")

        msg = str(exc.value)
        assert "fetch sp_widget/wid-1" in msg  # which call
        assert "str" in msg  # what came back
        assert "re-authenticate" in msg.lower()  # what to do

    def test_a_list_body_is_rejected(self):
        with pytest.raises(ValueError, match="expected a JSON object"):
            json_object(_resp([1, 2, 3]))

    def test_undecodable_body_reports_the_login_page(self):
        with pytest.raises(ValueError) as exc:
            json_object(_resp(raises=True, text="<!DOCTYPE html><title>Login"), "push")
        msg = str(exc.value)
        assert "did not return JSON" in msg
        assert "DOCTYPE" in msg  # the actual first bytes, for diagnosis


class TestJsonResult:
    def test_extracts_result(self):
        assert json_result(_resp({"result": [1]})) == [1]

    def test_default_when_absent(self):
        assert json_result(_resp({}), default=[]) == []

    def test_guard_still_applies(self):
        with pytest.raises(ValueError):
            json_result(_resp("nope"))
