"""Workflow Studio blockers, each measured live on PDI before it was fixed.

The builder is an iframe ($flow-designer.do) three shadow roots down the shell:
an expression on the top document, and a CSS selector from the page, never
reached it. Its rows re-render, so refs go stale and labels change.
"""

import pytest

from servicenow_mcp.browser import actions, snapshot
from servicenow_mcp.browser.evaluate import run_in_frames

# --- evaluate reaches the builder frame ------------------------------------


class _Doc:
    def __init__(self, value, url="https://test.service-now.com/now/workflow-studio"):
        self.value, self.url, self.calls = value, url, 0

    def evaluate(self, _script):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return {"ok": True, "value": self.value, "type": type(self.value).__name__}


class _Page(_Doc):
    def __init__(self, value, frames=()):
        super().__init__(value)
        self._frames = list(frames)

    @property
    def main_frame(self):
        return self

    @property
    def frames(self):
        return [self] + self._frames


def test_an_empty_top_document_answer_is_asked_of_the_frames():
    builder = _Doc(["Add Action", "Done"], url="https://test.service-now.com/$flow-designer.do?x=1")
    out = run_in_frames(_Page([], frames=[_Doc(None), builder]), expression="1")
    assert out["value"] == ["Add Action", "Done"] and out["frame"] == "$flow-designer.do"


def test_a_top_document_answer_is_not_second_guessed():
    frame = _Doc(["other"])
    out = run_in_frames(_Page(["top"], frames=[frame]), expression="1")
    assert out["value"] == ["top"] and frame.calls == 0 and "frame" not in out


def test_empty_everywhere_says_how_many_frames_were_asked():
    out = run_in_frames(_Page([], frames=[_Doc([]), _Doc({})]), expression="1")
    assert out["value"] == [] and out["frames_tried"] == 2


# --- snapshot target: frames, and a stale ref named as stale ----------------


class _Locator:
    def __init__(self, n, raises=None):
        self.n, self.raises = n, raises
        self.first = self

    def count(self):
        if self.raises:
            raise self.raises
        return self.n

    def aria_snapshot(self, mode=None):
        return '- application [ref=f4e65]:\n  - heading "Actions" [level=2] [ref=f4e67]'


class _SnapDoc:
    def __init__(self, matches=(), raises=None):
        self.matches, self.raises = set(matches), raises

    def locator(self, selector):
        return _Locator(1 if selector in self.matches else 0, self.raises)


class _SnapPage(_SnapDoc):
    def __init__(self, frames=(), **kw):
        super().__init__(**kw)
        self._frames = list(frames)

    @property
    def main_frame(self):
        return self

    @property
    def frames(self):
        return [self] + self._frames


def test_a_selector_snapshot_finds_the_element_inside_the_builder_frame():
    page = _SnapPage(frames=[_SnapDoc(matches={"[role=application]"})])
    out = snapshot.take(page, "[role=application]")
    assert out.get("complete") and "Actions" in out["text"]


def test_a_ref_from_an_older_snapshot_is_called_stale_not_a_raw_error():
    page = _SnapPage(raises=RuntimeError("Invalid frame in aria-ref selector"))
    out = snapshot.take(page, "f30e56")
    assert "older snapshot" in out["error"] and "Invalid frame" not in out["error"]


# --- a renamed step is still found by the head of its label -----------------


class _NearTarget:
    def __init__(self, labels):
        self.labels = labels

    def get_by_text(self, probe):
        return _Hits([])

    def locator(self, selector):
        needle = selector.split('*="', 1)[1].split('"', 1)[0].lower()
        return _Hits([lab for lab in self.labels if needle in lab.lower()])


class _Hits:
    def __init__(self, labels):
        self.labels = labels

    def count(self):
        return len(self.labels)

    def nth(self, i):
        return _El(self.labels[i])


class _El:
    def __init__(self, label):
        self.label = label

    def is_visible(self):
        return True

    def inner_text(self, timeout=None):
        return ""

    def get_attribute(self, name, timeout=None):
        return self.label if name == "aria-label" else None

    def evaluate(self, _js):
        return "button"

    def is_enabled(self):
        return True


class _NearPage(_NearTarget):
    main_frame = None
    frames: list = []


def test_a_labelled_step_is_found_by_the_part_of_its_name_that_stayed():
    renamed = "Add Action, Flow Logic, or Subflow after 9 - Check stage"
    page = _NearPage([renamed, "Add Action, Flow Logic, or Subflow after 3 - Update"])
    near = actions.near_matches(
        page, '[aria-label="Add Action, Flow Logic, or Subflow after 9 - If"]'
    )
    assert near and near[0]["text"] == f'[aria-label="{renamed}"]'


# --- choosing a row, and focus ----------------------------------------------


class _RowLocator:
    def __init__(self, role):
        self.role, self.done = role, []

    def get_attribute(self, name, timeout=None):
        return self.role

    def click(self, timeout=None):
        self.done.append("click")

    def press(self, key, timeout=None):
        self.done.append(f"press {key}")

    def focus(self, timeout=None):
        self.done.append("focus")


@pytest.fixture
def row(monkeypatch):
    holder = {}

    def _resolve(page, selector, timeout_ms, need_visible):
        return holder["loc"]

    monkeypatch.setattr(actions, "_resolve_locator", _resolve)
    monkeypatch.setattr(actions, "_wait_enabled", lambda loc: True)
    return holder


def _run(step):
    return actions._run_step(object(), actions.normalize([step])[0], 1, allow_server_script=True)


def test_enter_on_a_named_option_chooses_that_option(row):
    # Live: Enter at the "Requested Item" option picked the highlighted "Metric".
    row["loc"] = _RowLocator("option")
    out = _run({"action": "press", "key": "Enter", "selector": '[role=option]:has-text("Item")'})
    assert row["loc"].done == ["click"] and "highlighted" in out["clicked_row"]


def test_enter_on_anything_else_is_still_a_keypress(row):
    row["loc"] = _RowLocator("textbox")
    _run({"action": "press", "key": "Enter", "selector": "#name"})
    assert row["loc"].done == ["press Enter"]


def test_focus_puts_the_cursor_in_a_field_without_a_keypress(row):
    row["loc"] = _RowLocator("textbox")
    _run({"action": "focus", "selector": "#name"})
    assert row["loc"].done == ["focus"]
    with pytest.raises(ValueError, match="needs a selector"):
        actions.normalize([{"action": "focus"}])


# --- get_detail: stages per step, and the signature the summary dropped -----


def test_stages_land_on_the_steps_they_are_set_on(monkeypatch):
    from servicenow_mcp.tools import flow_designer_tools as fdt

    def _query(config, auth, *, table, query, fields, **kw):
        assert table == "sys_hub_flow_stage" and query == "flow=aaaa1111bbbb2222cccc3333dddd4444"
        # Measured on PDI: 0-based component positions ("4,7" = steps 5 and 8).
        return [
            {
                "label": "Fulfillment",
                "value": "fulfillment",
                "order": "2",
                "component_indexes": "4,7",
            },
            {"label": "Request Cancelled", "value": "x", "order": "7", "component_indexes": ""},
        ], 2

    monkeypatch.setattr(fdt, "sn_query_page", _query)
    structure = {
        "tree": [{"order": "5"}, {"order": "6"}],
        "tree_text": "[5]   ACTION Wait\n       in.x= 1\n[6]   ACTION Other",
        "variables": [{"name": "flag"}],
    }
    out = fdt._attach_stages_and_signature(
        structure, None, None, "aaaa1111bbbb2222cccc3333dddd4444"
    )
    assert out["stages"][0]["steps"] == [5, 8] and out["stages"][1]["steps"] == []
    assert out["tree"][0]["stage"] == "Fulfillment" and "stage" not in out["tree"][1]
    assert "[5]   ACTION Wait  [stage Fulfillment]" in out["tree_text"]
    assert "[6]   ACTION Other\n" not in out["tree_text"] and out["tree_text"].endswith("Other")


def test_unreadable_stages_are_not_reported_as_none(monkeypatch):
    from servicenow_mcp.tools import flow_designer_tools as fdt

    def _boom(*a, **k):
        raise RuntimeError("403")

    monkeypatch.setattr(fdt, "sn_query_page", _boom)
    out = fdt._attach_stages_and_signature({"variables": [{"name": "v"}]}, None, None, "x")
    assert out["stages"].startswith("not read")


def test_the_signature_is_fetched_when_the_summary_has_none(monkeypatch):
    from servicenow_mcp.tools import flow_designer_tools as fdt

    monkeypatch.setattr(fdt, "_fetch_flow_stages", lambda *a: [])
    monkeypatch.setattr(fdt, "_get_snapshot_id", lambda *a: "snap")
    monkeypatch.setattr(
        fdt,
        "_fetch_flow_signature",
        lambda c, a, flow_id, snapshot_id: {"variables": [{"name": "isdone", "type": "boolean"}]},
    )
    out = fdt._attach_stages_and_signature({"tree": []}, None, None, "x")
    assert out["signature"] == {"variables": [{"name": "isdone", "type": "boolean"}]}
