"""Every action-multiplexed tool must declare which fields each action uses.

Narrowing is opt-in by omission today: ``server.py`` reads
``getattr(params_model, "_FIELDS_BY_ACTION", None)`` and, when a model has no
map, narrows the ``action`` enum and leaves EVERY other field on the schema. A
``manage_*`` tool that forgets the map is therefore not broken — it is quietly
expensive, on every request, forever, and nothing says so.

That is what this file is: the thing that says so. It is a ratchet, not a rule —
a model may legitimately have nothing to narrow (one action, or every field used
by every action), and it opts out by name below with the reason written down.
Adding a name here is a decision someone made; forgetting the map is not.
"""

import inspect

import pytest

from servicenow_mcp.utils.registry import discover_tools

# Models whose actions genuinely share their whole field set, or that have too
# few actions for a map to buy anything. Each entry is a claim someone checked.
_NOTHING_TO_NARROW: dict[str, str] = {}

# Tools that multiplex on `action` and have NOT been mapped yet. This list may
# only ever shrink — that is the whole point of it.
#
# It is not an exemption. Writing sixteen maps in one sweep is how a map ends up
# omitting a field its action actually needs, and a narrowed schema that hides a
# required field does not waste tokens, it breaks the tool. Each of these gets
# mapped by someone who reads what its actions use.
#
# The test below fails when a tool that is NOT on this list ships without a map,
# which is the thing that had no detector at all before.
_NOT_YET_MAPPED = frozenset(
    {
        "manage_change",
        "manage_changeset",
        "manage_epic",
        "manage_group",
        "manage_incident",
        "manage_kb_article",
        "manage_portal_component",
        "manage_portal_layout",
        "manage_project",
        "manage_scrum_task",
        "manage_session_context",
        "manage_story",
        "manage_ui_policy",
        "manage_user",
        "query_local_graph",
        "sn_write",
    }
)


def _multiplexed_models():
    """(tool_name, params_model) for every tool whose params carry an `action`."""
    found = []
    for tool_name, definition in discover_tools().items():
        params_model = definition[1]
        fields = getattr(params_model, "model_fields", {})
        if "action" in fields:
            found.append((tool_name, params_model))
    return sorted(found)


def test_there_are_action_multiplexed_tools_to_check():
    """A discovery bug that found nothing would make every assertion below pass."""
    assert len(_multiplexed_models()) >= 5


@pytest.mark.parametrize("tool_name,params_model", _multiplexed_models())
def test_an_action_tool_declares_its_per_action_fields(tool_name, params_model):
    fields_by_action = getattr(params_model, "_FIELDS_BY_ACTION", None)

    if tool_name in _NOTHING_TO_NARROW:
        assert fields_by_action is None, (
            f"{tool_name} is listed as having nothing to narrow but now has a map — "
            "remove it from _NOTHING_TO_NARROW."
        )
        return

    if tool_name in _NOT_YET_MAPPED:
        # The ratchet's other half: once it IS mapped, the baseline entry has to
        # go, or the list stops describing anything and stops shrinking.
        assert not fields_by_action, (
            f"{tool_name} now declares _FIELDS_BY_ACTION — remove it from _NOT_YET_MAPPED "
            "so the list keeps meaning what it says."
        )
        return

    assert fields_by_action, (
        f"{tool_name} ({params_model.__name__}) multiplexes on `action` but declares no "
        "_FIELDS_BY_ACTION, so every action advertises every field on every request. "
        "Add the map, or add the tool to _NOTHING_TO_NARROW with the reason."
    )


@pytest.mark.parametrize("tool_name,params_model", _multiplexed_models())
def test_the_map_only_names_fields_the_model_actually_has(tool_name, params_model):
    """A typo'd field name narrows nothing and reads as narrowing something."""
    fields_by_action = getattr(params_model, "_FIELDS_BY_ACTION", None)
    if not fields_by_action:
        return

    known = set(getattr(params_model, "model_fields", {}))
    for action, names in fields_by_action.items():
        unknown = set(names) - known
        assert not unknown, (
            f"{tool_name}._FIELDS_BY_ACTION['{action}'] names fields the model does not "
            f"have: {sorted(unknown)}"
        )


@pytest.mark.parametrize("tool_name,params_model", _multiplexed_models())
def test_the_map_covers_every_action_the_enum_allows(tool_name, params_model):
    """An action missing from the map falls back to the full field set, silently."""
    fields_by_action = getattr(params_model, "_FIELDS_BY_ACTION", None)
    if not fields_by_action:
        return

    action_field = params_model.model_fields["action"]
    literals = getattr(action_field.annotation, "__args__", ())
    declared = {arg for arg in literals if isinstance(arg, str)}
    if not declared:
        pytest.skip(f"{tool_name} does not constrain `action` to a Literal")

    missing = declared - set(fields_by_action)
    assert not missing, (
        f"{tool_name} allows actions with no entry in _FIELDS_BY_ACTION: {sorted(missing)} — "
        "those actions advertise every field."
    )


def test_the_ratchet_is_reading_real_models():
    """Guards the guard: a model object with no fields would pass everything."""
    for _tool_name, params_model in _multiplexed_models():
        assert inspect.isclass(params_model)
        assert getattr(params_model, "model_fields", None)
