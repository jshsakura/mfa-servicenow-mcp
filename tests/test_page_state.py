"""page_state: what the page shows after a batch, as text instead of an image."""

from servicenow_mcp.browser.page_state import read_page_state


class _Frame:
    def __init__(self, state=None, raises=False):
        self.state, self.raises = state, raises

    def evaluate(self, _js):
        if self.raises:
            raise RuntimeError("Execution context was destroyed")
        return dict(self.state)


class _Page:
    def __init__(self, *frames):
        self.frames = list(frames)


def test_frames_merge_and_a_frames_own_focus_beats_the_iframe_tag():
    top = _Frame({"focused": {"tag": "iframe", "label": "gsft_main"}, "options": ["Open"]})
    form = _Frame(
        {
            "focused": {"tag": "input", "label": "State", "value": "Closed"},
            "options": ["Open", "Closed"],
            "alerts": ["Saved"],
        }
    )

    out = read_page_state(_Page(top, form))

    assert out["focused"] == {"tag": "input", "label": "State", "value": "Closed"}
    assert out["options"] == ["Open", "Closed"]
    assert out["alerts"] == ["Saved"]


def test_an_unreadable_page_says_so_instead_of_reading_as_empty():
    out = read_page_state(_Page(_Frame(raises=True)))

    assert "unread" in out and "destroyed" in out["unread"]


def test_a_read_page_with_nothing_open_is_empty():
    assert read_page_state(_Page(_Frame({}))) == {}


def test_one_dead_frame_does_not_hide_the_others():
    out = read_page_state(_Page(_Frame(raises=True), _Frame({"dialogs": ["Add a trigger"]})))

    assert out == {"dialogs": ["Add a trigger"]}


def test_an_outline_is_sent_once_then_named_until_it_changes():
    from servicenow_mcp.browser import page_state

    page_state._LAST_OUTLINE.clear()
    page = _Page(_Frame({"outline": ["1 Ask For Approval", "2 If Approved"]}))
    page.url = "https://test.service-now.com/now/workflow-studio/builder"

    first = read_page_state(page)
    second = read_page_state(page)
    page.frames = [_Frame({"outline": ["1 If Approved", "  2 then Ask For Approval"]})]
    third = read_page_state(page)

    assert first["outline"] == ["1 Ask For Approval", "2 If Approved"]
    assert second == {"outline_unchanged": 2}
    assert third["outline"][1] == "  2 then Ask For Approval"
