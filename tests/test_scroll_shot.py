"""A 'full' screenshot of a page whose scroller is a frame.

The bug these pin: ``full_page=True`` grows the TOP document, and on Next
Experience the top document never scrolls — measured on a live instance,
``scrollHeight == innerHeight`` exactly. So ``full`` returned one viewport and
called itself full.
"""

import io

import pytest

from servicenow_mcp.browser import capture as capture_module
from servicenow_mcp.browser import scroll_shot

PIL = pytest.importorskip("PIL.Image", reason="stitching needs the browser extra")


@pytest.fixture(autouse=True)
def _no_settle_pause(monkeypatch):
    """The real pause lets a sticky header repaint; nothing here repaints."""
    monkeypatch.setattr(scroll_shot, "SETTLE_S", 0.0)


def _png(width, height, colour):
    """Bytes of a solid image, the way page.screenshot() hands them over."""
    buffer = io.BytesIO()
    PIL.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeFrame:
    def __init__(self, url, *, scroll_h, client_h, top=0.0, box=None, colours=None):
        self.url = url
        self.scroll_h = scroll_h
        self.client_h = client_h
        self.top = top
        self.box = box or {"x": 0.0, "y": 0.0, "width": 100.0, "height": float(client_h)}
        self.colours = colours or [(10, 10, 10)]
        self.scrolls = []

    def evaluate(self, script, *args):
        if "scrollHeight" in script:
            return {"scrollH": self.scroll_h, "clientH": self.client_h, "top": self.top}
        if "scrollTop" in script:
            self.top = float(args[0])
            self.scrolls.append(self.top)
            return None
        return None

    def frame_element(self):
        return self

    def bounding_box(self):
        return dict(self.box)


class FakePage:
    """A shell that does not scroll, wrapping frames that might."""

    def __init__(self, url="https://dev.example.com/now/nav/ui/x", frames=(), scroll_h=743):
        self.url = url
        self._frames = list(frames)
        self.scroll_h = scroll_h
        self.client_h = 743
        self.shots = []
        self.scale = 1

    @property
    def main_frame(self):
        return self

    @property
    def frames(self):
        return [self] + self._frames

    def evaluate(self, script, *args):
        if "scrollHeight" in script:
            return {"scrollH": self.scroll_h, "clientH": self.client_h, "top": 0}
        return None

    def screenshot(self, clip=None, **kwargs):
        self.shots.append(dict(clip or {}))
        frame = self._frames[0]
        index = min(len(self.shots) - 1, len(frame.colours) - 1)
        height = int(clip["height"]) * self.scale
        return _png(int(clip["width"]) * self.scale, height, frame.colours[index])


def _frame(**kwargs):
    kwargs.setdefault("url", "https://dev.example.com/incident_list.do")
    return FakeFrame(**kwargs)


def test_a_shell_that_never_scrolls_is_not_treated_as_the_scroller():
    # The live reading that started this: scrollHeight == innerHeight exactly.
    assert scroll_shot.page_scrolls(FakePage(scroll_h=743)) is False
    assert scroll_shot.page_scrolls(FakePage(scroll_h=2000)) is True


def test_the_scrolling_frame_is_found_by_how_much_it_hides():
    small = _frame(scroll_h=800, client_h=700)
    big = _frame(scroll_h=4000, client_h=700)
    page = FakePage(frames=[small, big])

    assert scroll_shot.find_scrolling_frame(page) is big


def test_a_frame_that_fits_is_not_a_scroller():
    page = FakePage(frames=[_frame(scroll_h=700, client_h=700)])

    assert scroll_shot.find_scrolling_frame(page) is None


def test_a_cross_origin_frame_is_left_alone():
    # We cannot read its metrics, and driving another site's scroll position is
    # not this feature's business.
    stranger = _frame(url="https://ads.example.net/pixel", scroll_h=9000, client_h=100)
    page = FakePage(frames=[stranger])

    assert scroll_shot.find_scrolling_frame(page) is None


def test_the_screens_are_stitched_into_one_taller_image(tmp_path):
    frame = _frame(
        scroll_h=300,
        client_h=100,
        box={"x": 0.0, "y": 40.0, "width": 100.0, "height": 100.0},
        colours=[(255, 0, 0), (0, 255, 0), (0, 0, 255)],
    )
    page = FakePage(frames=[frame])
    destination = str(tmp_path / "shot.png")

    summary = scroll_shot.capture(page, destination=destination)

    assert summary["tiles"] == 3
    assert summary["height"] == 300
    assert "truncated" not in summary
    # Each screen was really scrolled to, and the clip followed the frame's box.
    assert frame.scrolls[:3] == [0.0, 100.0, 200.0]
    assert page.shots[0]["y"] == 40.0
    # Written as lossless WebP: same pixels, ~60% fewer bytes.
    assert summary["path"].endswith(".webp")
    with PIL.open(summary["path"]) as image:
        assert image.size == (100, 300)
        assert image.getpixel((50, 50)) == (255, 0, 0)
        assert image.getpixel((50, 150)) == (0, 255, 0)
        assert image.getpixel((50, 250)) == (0, 0, 255)


def test_the_scroll_position_is_put_back(tmp_path):
    frame = _frame(scroll_h=300, client_h=100, top=170.0, colours=[(1, 1, 1)] * 3)
    page = FakePage(frames=[frame])

    scroll_shot.capture(page, destination=str(tmp_path / "shot.png"))

    # Nothing on the page was changed; the one thing that moved is restored.
    assert frame.scrolls[-1] == 170.0
    assert frame.top == 170.0


def test_a_last_screen_that_overlaps_is_not_shown_twice(tmp_path):
    # 250px of content in 100px screens: the third screen can only scroll to
    # 150, so its top 50px repeat the second one.
    frame = _frame(scroll_h=250, client_h=100, colours=[(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    page = FakePage(frames=[frame])
    destination = str(tmp_path / "shot.png")

    summary = scroll_shot.capture(page, destination=destination)

    assert frame.scrolls[:3] == [0.0, 100.0, 150.0]
    assert summary["height"] == 250
    with PIL.open(summary["path"]) as image:
        assert image.size == (100, 250)


def test_a_device_pixel_ratio_does_not_shift_the_seam(tmp_path):
    # Screenshots come back at the DPR, so the overlap crop has to be computed
    # in the image's own pixels rather than in CSS ones.
    frame = _frame(scroll_h=250, client_h=100, colours=[(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    page = FakePage(frames=[frame])
    page.scale = 2
    destination = str(tmp_path / "shot.png")

    summary = scroll_shot.capture(page, destination=destination)

    assert summary["height"] == 500
    with PIL.open(summary["path"]) as image:
        assert image.size == (200, 500)


def test_a_page_too_long_to_stitch_says_what_it_left_out(tmp_path):
    frame = _frame(scroll_h=1000, client_h=100, colours=[(9, 9, 9)] * 10)
    page = FakePage(frames=[frame])

    summary = scroll_shot.capture(page, destination=str(tmp_path / "shot.png"), max_tiles=3)

    assert summary["tiles"] == 3
    # No silent cap: a shorter image that looks complete is the failure mode.
    assert "3 of 10 screens" in summary["truncated"]


def test_a_frame_that_grows_while_scrolling_is_reported(tmp_path):
    class Growing(FakeFrame):
        def evaluate(self, script, *args):
            result = super().evaluate(script, *args)
            if "scrollHeight" in script:
                self.scroll_h += 400  # lazy loading, one screen at a time
            return result

    frame = Growing(
        "https://dev.example.com/list.do", scroll_h=200, client_h=100, colours=[(3, 3, 3)] * 4
    )
    page = FakePage(frames=[frame])

    summary = scroll_shot.capture(page, destination=str(tmp_path / "shot.png"))

    assert "lazy loading" in summary["grew_while_scrolling"]


def test_no_scrolling_frame_means_fall_back_rather_than_a_wrong_image(tmp_path):
    page = FakePage(frames=[_frame(scroll_h=100, client_h=100)])

    assert scroll_shot.capture(page, destination=str(tmp_path / "shot.png")) is None


# ---------------------------------------------------------------------------
# capture._screenshot — bytes on disk, and who is in the picture
# ---------------------------------------------------------------------------


class ShotPage(FakePage):
    """A page whose only job is to hand over screenshot bytes."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.evaluated = []

    def evaluate(self, script, *args):
        self.evaluated.append(script)
        return super().evaluate(script, *args)

    def screenshot(self, clip=None, full_page=False, **kwargs):
        self.shots.append({"clip": clip, "full_page": full_page})
        if clip:
            return super().screenshot(clip=clip, **kwargs)
        return _png(120, 60, (200, 30, 30))


class TrimTab:
    """A tab that may or may not be holding somebody's input."""

    def __init__(self, url, dirty=()):
        self.url = url
        self.dirty = list(dirty)
        self.closed = False

    def evaluate(self, script, *args):
        if "p.dirty()" in script:
            return {"fields": self.dirty, "observedFromStart": True}
        return None

    def close(self):
        self.closed = True


class TrimContext:
    def __init__(self, pages):
        self.pages = list(pages)


def test_tabs_below_the_cap_are_left_alone():
    tabs = [TrimTab(f"https://dev.example.com/{i}.do") for i in range(3)]

    assert capture_module._trim_tabs(TrimContext(tabs), keep=tabs[-1]) == {}
    assert not any(tab.closed for tab in tabs)


def test_the_oldest_empty_tabs_are_closed_once_over_the_cap():
    # Tabs accumulated forever: navigate opens them, and nothing removed them.
    tabs = [TrimTab(f"https://dev.example.com/{i}.do") for i in range(capture_module.MAX_TABS + 2)]

    note = capture_module._trim_tabs(TrimContext(tabs), keep=tabs[-1])

    assert len(note["closed_tabs"]) == 2
    assert [tab.closed for tab in tabs[:2]] == [True, True]
    assert tabs[-1].closed is False, "never the tab just opened"


def test_a_tab_holding_input_is_never_closed():
    # Closing is destructive, so even a GUESSED dirty field protects the tab —
    # a stricter bar than the "a guess only steps aside" rule for opening one.
    tabs = [TrimTab(f"https://dev.example.com/{i}.do") for i in range(capture_module.MAX_TABS + 2)]
    tabs[0].dirty = ["short_description"]

    note = capture_module._trim_tabs(TrimContext(tabs), keep=tabs[-1])

    assert tabs[0].closed is False
    assert tabs[0].url not in note["closed_tabs"]


def test_trimming_takes_this_instances_duplicates_before_another_instances_tab():
    """One window holds every instance now, so "oldest" is not enough.

    The tabs that made the window hard to work in are the ones piling up on the
    instance being driven; another instance's single tab happening to be older
    is not a reason to take it first.
    """
    other = TrimTab("https://test.example.com/home.do")
    mine = [TrimTab(f"https://dev.example.com/{i}.do") for i in range(capture_module.MAX_TABS + 1)]

    note = capture_module._trim_tabs(
        TrimContext([other, *mine]), keep=mine[-1], instance_host="dev.example.com"
    )

    assert len(note["closed_tabs"]) == 2
    assert other.closed is False, "the other instance's only tab was the oldest, and survives"
    assert [tab.closed for tab in mine[:2]] == [True, True]


def test_a_cap_that_could_not_bite_says_so():
    # A cap that silently gives up looks identical to one that worked.
    tabs = [
        TrimTab(f"https://dev.example.com/{i}.do", dirty=["x"])
        for i in range(capture_module.MAX_TABS + 2)
    ]

    note = capture_module._trim_tabs(TrimContext(tabs), keep=tabs[-1])

    assert "closed_tabs" not in note
    assert "none could be closed" in note["tabs_note"]


def _badge_calls(page):
    return [s for s in page.evaluated if "badge" in s.lower()]


def test_a_screenshot_is_written_as_lossless_webp(tmp_path):
    # Measured on a real ServiceNow screenshot: 64KB PNG -> 26KB WebP at a
    # maximum per-channel difference of zero. Nothing is resampled, so the text
    # is exactly as sharp as it was.
    page = ShotPage(scroll_h=2000, frames=[_frame(scroll_h=100, client_h=100)])

    path, note = capture_module._screenshot(
        page, mode="viewport", selector=None, destination=str(tmp_path / "shot.png")
    )

    assert path.endswith(".webp")
    assert note is None
    with PIL.open(path) as image:
        assert image.size == (120, 60)
        assert image.getpixel((60, 30)) == (200, 30, 30)


def test_a_single_shot_keeps_the_badge_in_the_picture(tmp_path):
    # Which window, which instance, which account, impersonating or not — that
    # is what the badge answers, and cropping it out threw it away every time.
    page = ShotPage(scroll_h=2000, frames=[_frame(scroll_h=100, client_h=100)])

    capture_module._screenshot(
        page, mode="viewport", selector=None, destination=str(tmp_path / "shot.png")
    )

    assert _badge_calls(page) == []


def test_a_scrolling_capture_hides_the_badge_for_the_whole_scroll(tmp_path):
    # position:fixed rides every screen, so it would come out stamped down the
    # stitched image once per tile.
    frame = _frame(scroll_h=300, client_h=100, colours=[(1, 2, 3)] * 3)
    page = ShotPage(scroll_h=743, frames=[frame])

    path, note = capture_module._screenshot(
        page, mode="full", selector=None, destination=str(tmp_path / "shot.png")
    )

    assert note["tiles"] == 3
    assert path.endswith(".webp")
    hides = _badge_calls(page)
    assert len(hides) == 2, "hidden once before the scroll, restored once after"
