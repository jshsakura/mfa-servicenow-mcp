"""A 'full' screenshot of a page whose scroller is a frame.

The bug these pin: ``full_page=True`` grows the TOP document, and on Next
Experience the top document never scrolls — measured on a live instance,
``scrollHeight == innerHeight`` exactly. So ``full`` returned one viewport and
called itself full.
"""

import io

import pytest

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
    with PIL.open(destination) as image:
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
    with PIL.open(destination) as image:
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
    with PIL.open(destination) as image:
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
