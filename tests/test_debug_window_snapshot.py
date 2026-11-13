"""Element outline with refs (inspect/act snapshot=...) and acting on a ref."""

from typing import Any, Dict, List

import pytest

from servicenow_mcp.browser import actions, snapshot
from servicenow_mcp.tools.browser_debug_tools import (
    ActInDebugWindowParams,
    InspectDebugWindowParams,
)

PAGE = """- generic [ref=e1]:
  - textbox "Short description" [ref=e3]
  - iframe [ref=e6]:
    - button "Save" [ref=f1e2]"""


class _Loc:
    def __init__(self, page: "_Page", selector: str) -> None:
        self.page, self.selector = page, selector

    def count(self) -> int:
        if self.selector in self.page.raise_on:
            raise RuntimeError('Invalid frame in aria-ref selector "x"\nlog')
        return 1 if self.selector in self.page.present else 0

    @property
    def first(self) -> "_Loc":
        return self

    def aria_snapshot(self, mode: str = "default") -> str:
        self.page.calls.append((self.selector, mode))
        return self.page.region


class _Page:
    def __init__(self, text: str = PAGE, present: Any = (), raise_on: Any = ()) -> None:
        self.text, self.region = text, '- button "Save" [ref=f1e2]'
        self.present, self.raise_on = set(present), set(raise_on)
        self.calls: List[Any] = []
        self.frames: List[Any] = []
        self.main_frame = None

    def aria_snapshot(self, mode: str = "default") -> str:
        self.calls.append(("page", mode))
        return self.text

    def locator(self, selector: str) -> _Loc:
        return _Loc(self, selector)


class _OldPage(_Page):
    def aria_snapshot(self) -> str:  # type: ignore[override]  # pre-AI-mode Playwright
        return ""


class TestAsSelector:
    @pytest.mark.parametrize("raw", ["e5", "f1e2", "f12e304"])
    def test_bare_ref_becomes_aria_ref(self, raw: str) -> None:
        assert snapshot.as_selector(raw) == "aria-ref=" + raw

    @pytest.mark.parametrize("raw", ["#e5", "button", "text=e5", "aria-ref=e5", "e5 > a", "em"])
    def test_anything_else_is_left_alone(self, raw: str) -> None:
        assert snapshot.as_selector(raw) == raw

    def test_normalize_maps_selector_and_drop_target(self) -> None:
        [step] = actions.normalize(
            [{"action": "drag", "selector": "e5", "to": "f1e2", "value": "center"}]
        )
        assert step["selector"] == "aria-ref=e5"
        assert step["to"] == "aria-ref=f1e2"


class TestTake:
    def test_whole_page_in_ai_mode(self) -> None:
        page = _Page()
        out = snapshot.take(page, "page")
        assert out == {"text": PAGE, "complete": True}
        assert page.calls == [("page", "ai")]

    def test_region_by_bare_ref(self) -> None:
        page = _Page(present={"aria-ref=e6"})
        out = snapshot.take(page, "e6")
        assert out["complete"] is True
        assert page.calls == [("aria-ref=e6", "ai")]

    def test_region_not_found_is_an_error_not_an_empty_outline(self) -> None:
        out = snapshot.take(_Page(), "#nope")
        assert "No element matched '#nope'" in out["error"]
        assert "text" not in out

    def test_old_playwright_says_upgrade(self) -> None:
        out = snapshot.take(_OldPage(), "page")
        assert "Upgrade playwright" in out["error"]

    def test_stale_ref_is_reported(self) -> None:
        out = snapshot.take(_Page(raise_on={"aria-ref=f1e2"}), "f1e2")
        assert out["error"].startswith("Snapshot of 'f1e2' failed: Invalid frame")

    def test_oversized_page_keeps_whole_levels_and_says_so(self, monkeypatch: Any) -> None:
        deep = "\n".join(
            ["- main [ref=e1]:"]
            + [f'  - region "R{i}" [ref=e{10 + i}]:' for i in range(3)]
            + [f'    - button "B{i}" [ref=e{100 + i}]' for i in range(200)]
        )
        monkeypatch.setattr(snapshot, "MAX_SNAPSHOT_CHARS", 400)
        out = snapshot.take(_Page(text=deep), "page")
        assert out["complete"] is False
        assert "button" not in out["text"]  # level 2 does not fit, so none of it
        assert out["text"].count("region") == 3  # level 1 is whole
        assert "depth 1 only" in out["note"] and "snapshot='e12'" in out["note"]

    def test_nothing_fits_shows_nothing_rather_than_a_partial_level(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(snapshot, "MAX_SNAPSHOT_CHARS", 5)
        out = snapshot.take(_Page(), "page")
        assert out["text"] == "" and out["complete"] is False
        assert "depth -1" in out["note"]


class TestResolveRef:
    def test_present_ref_resolves_without_frame_search(self) -> None:
        page = _Page(present={"aria-ref=f1e2"})
        loc = actions._resolve_locator(page, "aria-ref=f1e2", 5000, need_visible=True)
        assert loc.selector == "aria-ref=f1e2"

    @pytest.mark.parametrize("raise_on", [set(), {"aria-ref=e9"}])
    def test_stale_ref_fails_at_once_and_says_take_a_new_snapshot(self, raise_on: Any) -> None:
        page = _Page(raise_on=raise_on)
        step: Dict[str, Any] = actions.normalize([{"action": "click", "selector": "e9"}])[0]
        with pytest.raises(actions.ActionError) as err:
            actions._run_step(page, step, 1)
        assert "not on the page any more" in str(err.value)
        assert "Nothing was done" in str(err.value)


class TestParams:
    def test_inspect_and_act_accept_snapshot(self) -> None:
        assert InspectDebugWindowParams(snapshot="page").snapshot == "page"
        act = ActInDebugWindowParams(actions=[{"action": "click", "selector": "e5"}], snapshot="e1")
        assert act.snapshot == "e1"


class TestLean:
    def test_link_urls_and_pointer_flags_are_dropped(self) -> None:
        text = (
            '- link "INC0010001" [ref=e7] [cursor=pointer]:\n'
            "  - /url: /incident.do?sys_id=aaaa1111bbbb2222cccc3333dddd4444&sysparm_view=\n"
            '- button "Save" [ref=e8] [cursor=pointer]'
        )
        out = snapshot.take(_Page(text=text), "page")
        assert out["text"] == '- link "INC0010001" [ref=e7]:\n- button "Save" [ref=e8]'
