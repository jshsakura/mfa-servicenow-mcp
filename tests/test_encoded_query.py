"""A caller's value must not be able to become query STRUCTURE.

The failure this prevents is not an error — it is rows. ServiceNow drops an
encoded-query condition it cannot parse and answers with what is left, so a
value carrying `^` widens the query and the widened result reads as an answer.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from servicenow_mcp.services import catalog as catalog_service
from servicenow_mcp.services import incident as incident_service
from servicenow_mcp.utils.encoded_query import SafeValue, encoded_value, safe_value


def test_the_condition_separator_cannot_survive_in_a_value():
    result = safe_value("open^ORstate=7")

    assert result.value == "openORstate=7"
    assert result.removed == ("^",)
    assert result.changed is True


def test_a_clean_value_is_passed_through_untouched_and_says_so():
    result = safe_value("Network outage")

    assert result.value == "Network outage"
    assert result.removed == ()
    assert result.changed is False
    assert result.note() == "", "nothing removed is nothing to report"


def test_equals_and_comma_are_deliberately_left_alone():
    """`=` cannot start a new condition, so removing it only corrupts values.

    Two older helpers in this repo strip it. That is not a reason to.
    """
    assert safe_value("a=b, c").value == "a=b, c"


def test_newlines_go_because_they_break_the_request_not_the_query():
    assert safe_value("one\ntwo\r").value == "onetwo"


def test_none_becomes_empty_rather_than_the_word_none():
    """A filter built from the literal text "None" matches nothing and looks real."""
    assert safe_value(None).value == ""
    assert encoded_value(None) == ""


def test_the_note_names_the_field_and_what_was_actually_searched():
    note = safe_value("a^b").note(field="category")

    assert "category" in note
    assert "'ab'" in note, "the caller has to be told what was searched instead"


def test_str_of_a_safe_value_is_the_value_not_the_wrapper():
    # An f-string that reached for the dataclass would embed "SafeValue(...)"
    # into the query — a silent, and very confusing, filter.
    assert f"x={SafeValue('y')}" == "x=y"


# ---------------------------------------------------------------------------
# The two service modules an adversarial review found with no handling at all
# ---------------------------------------------------------------------------


def _page(monkeypatch, module, captured):
    def _fake(config, auth_manager, **kwargs):
        captured["query"] = kwargs["query"]
        return [], None

    monkeypatch.setattr(module, "sn_query_page", _fake)


def _config():
    return SimpleNamespace(instance_url="https://test.service-now.com", api_url="")


def test_an_incident_filter_cannot_smuggle_a_second_condition(monkeypatch):
    captured = {}
    _page(monkeypatch, incident_service, captured)

    result = incident_service.get(_config(), MagicMock(), state="1^ORstate=7", limit=1, offset=0)

    assert captured["query"] == "state=1ORstate=7"
    assert "^OR" not in captured["query"]
    assert result["filter_notes"], "a cleaned filter is never silent"


def test_a_catalog_search_term_cannot_smuggle_one_either(monkeypatch):
    captured = {}
    _page(monkeypatch, catalog_service, captured)

    result = catalog_service.list_items(_config(), MagicMock(), query="vpn^active=true")

    assert "^active=true" not in captured["query"]
    assert result["filter_notes"]


def test_an_ordinary_search_reports_no_filter_notes(monkeypatch):
    captured = {}
    _page(monkeypatch, catalog_service, captured)

    result = catalog_service.list_items(_config(), MagicMock(), query="vpn")

    assert captured["query"] == "short_descriptionLIKEvpn^ORnameLIKEvpn"
    assert "filter_notes" not in result
