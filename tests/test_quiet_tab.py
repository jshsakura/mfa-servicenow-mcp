"""A new debug-window tab must not take the person's keyboard and mouse.

Measured on macOS: new_page() and bring_to_front() made the debug window the
front app; Target.createTarget with background=true did not.
"""

from contextlib import contextmanager
from types import SimpleNamespace

from servicenow_mcp.browser import quiet_tab


class _Session:
    def __init__(self, fail=False):
        self.sent, self.fail, self.detached = [], fail, False

    def send(self, method, params):
        if self.fail:
            raise RuntimeError("Target.createTarget not allowed")
        self.sent.append((method, params))

    def detach(self):
        self.detached = True


class _Context:
    def __init__(self):
        self.new_pages = 0
        self.background_tab = object()

    @contextmanager
    def expect_page(self, timeout=None):
        yield SimpleNamespace(value=self.background_tab)

    def new_page(self):
        self.new_pages += 1
        return "foreground tab"


def test_a_new_tab_is_created_in_the_background():
    session, context = _Session(), _Context()
    browser = SimpleNamespace(new_browser_cdp_session=lambda: session)
    assert quiet_tab.open_tab(browser, context) is context.background_tab
    assert session.sent == [("Target.createTarget", {"url": "about:blank", "background": True})]
    assert session.detached and context.new_pages == 0


def test_without_a_background_tab_a_normal_one_still_opens():
    context = _Context()
    browser = SimpleNamespace(new_browser_cdp_session=lambda: _Session(fail=True))
    assert quiet_tab.open_tab(browser, context) == "foreground tab"
    assert quiet_tab.open_tab(SimpleNamespace(), context) == "foreground tab"


class _Page:
    def __init__(self):
        self.fronted = 0

    def bring_to_front(self):
        self.fronted += 1


def test_the_tab_comes_forward_only_while_the_window_is_in_front(monkeypatch):
    for front, expected in ((True, 1), (False, 0), (None, 0)):
        monkeypatch.setattr(quiet_tab, "window_is_front", lambda pid, f=front: f)
        page = _Page()
        assert quiet_tab.show_if_watched(page, 4242) is bool(expected)
        assert page.fronted == expected


def test_the_front_app_is_compared_by_pid(monkeypatch):
    out = {"front": "ASN:0x0-0x189189:\n", "info": '"pid"=4242\n'}

    def _run(args, **kw):
        return SimpleNamespace(stdout=out["front"] if args[1] == "front" else out["info"])

    monkeypatch.setattr(quiet_tab.sys, "platform", "darwin")
    monkeypatch.setattr(quiet_tab.subprocess, "run", _run)
    assert quiet_tab.window_is_front(4242) is True
    assert quiet_tab.window_is_front(1111) is False
    out["info"] = "nothing useful"
    assert quiet_tab.window_is_front(4242) is None


def test_off_macos_the_front_app_is_unknown_not_ours(monkeypatch):
    monkeypatch.setattr(quiet_tab.sys, "platform", "linux")
    assert quiet_tab.window_is_front(4242) is None
