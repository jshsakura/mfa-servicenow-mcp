"""ServiceNow's identifier-first login, end to end, in a real Chromium.

Measured on a PDI: step 1 asks only for the username (``input#user_name`` +
``button#sysverb_ifl_login`` "Next", no password field), step 2
``ifl_password_login.do`` shows ``input#user_password`` beside a HIDDEN
``input#user_name`` and ``button#sysverb_ifl_password_login``. The debug
window's auto-login waited for a password field, never saw one, and reported
``no_login_form`` on a page that plainly was one.

The pages below reproduce those shapes on a local HTTP server; the window is a
real Chromium reached over CDP, exactly as ``auto_login`` reaches the debug
window. CI has no browser, so these skip there.
"""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator, List
from urllib.parse import parse_qs, urlparse

import pytest

from servicenow_mcp.auth._browser_dom import _ifl_identifier_step
from servicenow_mcp.browser import _offload, login
from servicenow_mcp.browser.window import WindowState

STEP_ONE = """<!doctype html><html><head><title>Log in to your account</title></head><body>
<form method="post" action="/ifl_password_login.do">
  <input id="user_name" name="user_name" type="text" autocomplete="off">
  <button id="sysverb_ifl_login" name="not_important" type="submit">Next</button>
</form></body></html>"""

STEP_TWO = """<!doctype html><html><head><title>Enter your password</title></head><body>
<form method="post" action="/login.do">
  <input id="user_name" name="user_name" type="hidden" value="{user}">
  <input id="user_password" name="user_password" type="password">
  <button id="mask_icon" type="button">Show</button>
  <button id="sysverb_ifl_password_login" name="not_important" type="submit">Log In</button>
</form></body></html>"""

REFUSED = STEP_TWO.replace(
    "<form",
    '<div class="outputmsg_error" role="alert">User name or password invalid.</div><form',
    1,
)

SIGNED_IN = "<!doctype html><html><head><title>Home</title></head><body>signed in</body></html>"

# A signed-in page that happens to hold a user_name field: NOT a login.
USER_FORM = """<!doctype html><html><body><form>
<input id="user_name" name="user_name"><button type="submit">Save</button></form></body></html>"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Site:
    def __init__(self, redirect_to: str = "", refuse_to_step_one: bool = False) -> None:
        self.posts: List[str] = []
        self.redirect_to = redirect_to
        self.refuse_to_step_one = refuse_to_step_one
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, body: str, status: int = 200, headers: Any = ()) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/html")
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body.encode())

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                self._send(USER_FORM if path == "/sys_user.do" else STEP_ONE)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                form = parse_qs(self.rfile.read(length).decode())
                path = urlparse(self.path).path
                site.posts.append(path)
                if path == "/ifl_password_login.do":
                    if site.redirect_to:
                        self._send("", 302, [("Location", site.redirect_to)])
                        return
                    self._send(STEP_TWO.format(user=form.get("user_name", [""])[0]))
                elif path == "/login.do":
                    # Measured: a refusal returns the PASSWORD page with an error.
                    ok = form.get("user_password", [""])[0] == "s3cret"
                    refused = STEP_ONE if site.refuse_to_step_one else REFUSED.format(user="")
                    self._send(SIGNED_IN if ok else refused)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture()
def window(tmp_path: Any) -> Iterator[Any]:
    sync_api = pytest.importorskip("playwright.sync_api")
    port = _free_port()
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=[f"--remote-debugging-port={port}"])
        except Exception as exc:  # noqa: BLE001 - no browser installed (CI)
            pytest.skip(f"Chromium not available: {exc}")
        page = browser.new_page()
        try:
            yield port, page
        finally:
            # auto_login runs on the shared offload worker, which now holds a
            # REAL driver; later tests assume a fresh one.
            _offload._reset_worker_for_tests()
            browser.close()


def _state(port: int, site: _Site) -> WindowState:
    return WindowState(
        pid=1, port=port, profile_dir="/tmp/ifl-test", instance_url=site.url, started_at=1.0
    )


def test_a_two_step_login_is_completed(window: Any, tmp_path: Any) -> None:
    port, page = window
    site = _Site()
    try:
        page.goto(f"{site.url}/navpage.do")
        result = login.auto_login(
            _state(port, site),
            credentials=("alice", "s3cret"),
            marker_path=str(tmp_path / "m.json"),
        )
        assert result["status"] == "submitted", result
        assert site.posts == ["/ifl_password_login.do", "/login.do"]
        assert page.title() == "Home"
    finally:
        site.close()


@pytest.mark.parametrize("back_to_step_one", [False, True], ids=["password_page", "step_one"])
def test_a_wrong_password_on_step_two_is_still_a_refusal(
    window: Any, tmp_path: Any, back_to_step_one: bool
) -> None:
    port, page = window
    site = _Site(refuse_to_step_one=back_to_step_one)
    try:
        page.goto(f"{site.url}/navpage.do")
        result = login.auto_login(
            _state(port, site),
            credentials=("alice", "wrong"),
            marker_path=str(tmp_path / "m.json"),
        )
        assert result["status"] == "rejected", result
        assert login.already_attempted(str(tmp_path / "m.json"), _state(port, site))
    finally:
        site.close()


def test_a_redirect_after_next_gets_no_password(window: Any, tmp_path: Any) -> None:
    port, page = window
    idp = _Site()
    site = _Site(
        redirect_to=f"http://localhost:{idp.server.server_address[1]}/ifl_password_login_idp"
    )
    try:
        # The IdP happens to show a password form too; it must not get ours.
        page.goto(f"{site.url}/navpage.do")
        result = login.auto_login(
            _state(port, site),
            credentials=("alice", "s3cret"),
            marker_path=str(tmp_path / "m.json"),
        )
        assert result["status"] == "identifier_redirected", result
        assert "/login.do" not in site.posts and "/login.do" not in idp.posts
        assert not login.already_attempted(str(tmp_path / "m.json"), _state(port, site))
    finally:
        site.close()
        idp.close()


def test_a_signed_in_form_with_a_user_name_field_is_not_a_login(window: Any) -> None:
    _, page = window
    site = _Site()
    try:
        page.goto(f"{site.url}/sys_user.do")
        assert _ifl_identifier_step([page]) is None
        assert login._wait_for_login_form(page) is False
    finally:
        site.close()
