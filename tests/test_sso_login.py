"""``auth_type: "sso"`` — browser auth that signs in through the SSO locator page.

Two halves. The config half: "sso" is a spelling of browser auth that carries
an explicit marker, drops the password, and points the login page at the
instance's own ``login_locate_sso.do``. The debug-window half: the user ID goes
into the locator's field and Submit is clicked — nothing is ever typed into a
password field, on the instance or at the identity provider.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from test_debug_window import FakePage, _state

from servicenow_mcp.browser import login
from servicenow_mcp.cli import create_config
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig
from servicenow_mcp.utils.instances import split_sso_auth_type, sso_locator_url

_LOCATOR = "https://dev.example.com/login_locate_sso.do"
_SSO_FIELD = "input#sso_selector_id"
_SSO_SUBMIT = "button[onclick*='locateSSO']"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_sso_is_browser_auth_with_an_explicit_marker():
    assert split_sso_auth_type("SSO") == ("browser", "sso")
    assert split_sso_auth_type("browser") == ("browser", "password")
    assert split_sso_auth_type("basic") == ("basic", "password")


def test_the_locator_url_hangs_off_the_instance_root():
    assert sso_locator_url("https://dev.example.com/") == _LOCATOR


def _named(base_auth):
    from servicenow_mcp.server import ServiceNowMCP

    fake = SimpleNamespace(config=SimpleNamespace(auth=base_auth))
    return lambda entry: ServiceNowMCP._auth_for_instance_entry(fake, entry)


def _browser_base(**kwargs):
    return AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig(**kwargs))


def test_a_named_sso_entry_never_keeps_a_password(monkeypatch):
    # Not even one inherited from the globals — in this mode a password has
    # nowhere legitimate to go.
    monkeypatch.setenv("SERVICENOW_PASSWORD", "global_pw")
    build = _named(_browser_base())

    auth = build({"url": "https://dev.example.com", "auth_type": "sso", "username": "alice"})

    assert auth.type == AuthType.BROWSER
    assert auth.browser.login == "sso"
    assert auth.browser.username == "alice"
    assert auth.browser.password is None
    assert auth.browser.login_url == _LOCATOR


def test_a_password_written_on_an_sso_entry_is_dropped_with_a_warning(caplog):
    build = _named(_browser_base())

    auth = build(
        {
            "url": "https://dev.example.com",
            "auth_type": "sso",
            "username": "alice",
            "password": "local_pw",
        }
    )

    assert auth.browser.password is None
    assert "password is ignored" in caplog.text


def test_an_sso_entry_does_not_inherit_another_hosts_login_url():
    build = _named(_browser_base(login_url="https://prod.example.com/login.do"))

    auth = build({"url": "https://dev.example.com", "auth_type": "sso", "username": "alice"})

    assert auth.browser.login_url == _LOCATOR


def test_an_sso_entry_keeps_its_own_login_url_override():
    build = _named(_browser_base())
    custom = "https://dev.example.com/custom_sso.do"

    auth = build(
        {"url": "https://dev.example.com", "auth_type": "sso", "username": "a", "login_url": custom}
    )

    assert auth.browser.login_url == custom


def test_an_entry_that_says_nothing_follows_an_sso_base():
    build = _named(_browser_base(username="alice", login="sso", login_url=_LOCATOR))

    auth = build({"url": "https://test.example.com"})

    assert auth.browser.login == "sso"
    assert auth.browser.login_url == "https://test.example.com/login_locate_sso.do"


def test_an_explicit_browser_entry_under_an_sso_base_is_a_password_login():
    build = _named(_browser_base(login="sso"))

    auth = build({"url": "https://test.example.com", "auth_type": "browser"})

    assert auth.browser.login == "password"


def _browser_args():
    args = MagicMock()
    args.instance_url = None
    args.auth_type = "browser"
    args.browser_username = None
    args.browser_password = None
    args.browser_login_url = None
    args.browser_probe_path = None
    args.browser_headless = "false"
    args.browser_timeout = 120
    args.browser_user_data_dir = None
    args.browser_session_ttl = 30
    args.debug = False
    args.timeout = 30
    args.server_name = "ServiceNow"
    return args


@patch.dict(
    os.environ,
    {
        "SERVICENOW_ACTIVE_INSTANCE": "qa",
        "SERVICENOW_INSTANCE_CONFIG": json.dumps(
            {
                "qa": {
                    "url": "https://dev.example.com",
                    "auth_type": "sso",
                    "username": "alice",
                    "password": "local_pw",
                }
            }
        ),
    },
    clear=True,
)
def test_the_active_sso_instance_signs_in_on_the_locator_page():
    config = create_config(_browser_args())

    assert config.auth.type == AuthType.BROWSER
    assert config.auth.browser.login == "sso"
    assert config.auth.browser.username == "alice"
    assert config.auth.browser.password is None
    assert config.auth.browser.login_url == _LOCATOR


# ---------------------------------------------------------------------------
# What the debug window is handed
# ---------------------------------------------------------------------------


def _sso_config(username="alice", login_url=_LOCATOR, basic=None):
    browser = SimpleNamespace(username=username, password=None, login="sso", login_url=login_url)
    return SimpleNamespace(auth=SimpleNamespace(browser=browser, basic=basic))


def test_sso_mode_hands_out_no_password_even_from_the_basic_section():
    config = _sso_config(basic=SimpleNamespace(username="bob", password="a-secret"))

    assert login.saved_credentials(config) is None
    assert login.sso_login(config) == ("alice", _LOCATOR)
    assert login.configured_username(config) == "alice"


def test_sso_without_a_user_id_has_nothing_to_send():
    assert login.sso_login(_sso_config(username=None)) is None


def test_a_password_profile_is_not_sso():
    config = SimpleNamespace(
        auth=SimpleNamespace(
            browser=SimpleNamespace(username="alice", password="pw", login="password"),
            basic=None,
        )
    )

    assert login.sso_login(config) is None
    assert login.configured_username(config) == "alice"


def test_a_locator_on_another_host_is_not_where_this_window_signs_in():
    assert login._locator_url("https://prod.example.com/x.do", "dev.example.com") == _LOCATOR
    assert login._locator_url(_LOCATOR, "dev.example.com") == _LOCATOR


# ---------------------------------------------------------------------------
# Driving the locator page
# ---------------------------------------------------------------------------


class _SsoPage(FakePage):
    """A tab that answers the locator's Submit the way the instance would.

    ``outcome`` is what Submit does: ``redirect`` moves the tab off the locator,
    ``error`` posts the in-page error message, ``nothing`` leaves it be.
    """

    def __init__(self, known, url, outcome="redirect"):
        super().__init__(known=known, url=url)
        self.outcome = outcome
        self.visited = []

    def goto(self, url, wait_until=None, timeout=None):
        self.visited.append(url)
        self.url = url
        self.known = {_SSO_FIELD, _SSO_SUBMIT, "button[type='submit']"}

    def click(self, selector):
        super().click(selector)
        if self.outcome == "redirect":
            self.url = "https://idp.example.org/authorize?x=1"
            self.known = {"input[type='password']"}
        elif self.outcome == "error":
            self.known = self.known | {".outputmsg_error"}


@pytest.fixture()
def _fast(monkeypatch):
    monkeypatch.setattr(login, "_VERDICT_POLL_S", 0.0)
    monkeypatch.setattr(login, "SSO_VERDICT_S", 0.2)


def _typed(page):
    return [call for call in page.calls if call[0] == "fill"]


def test_the_locator_gets_the_user_id_and_its_submit_is_clicked(tmp_path, _fast):
    page = _SsoPage({_SSO_FIELD, _SSO_SUBMIT}, _LOCATOR)
    marker = str(tmp_path / "login.json")

    result = login._sso_sign_in(page, _state(), user="alice", locator=_LOCATOR, marker_path=marker)

    assert result["status"] == "sso_redirected"
    assert _typed(page) == [("fill", _SSO_FIELD, "alice")]
    assert ("click", _SSO_SUBMIT) in page.calls
    # Handed on to the IdP: a session that expires later gets a fresh hand-off.
    assert login.already_attempted(marker, _state()) is False


def test_the_local_login_form_is_never_filled_it_is_left_for_the_locator(tmp_path, _fast):
    # The instance's own form is the wrong door in SSO mode: its password is not
    # the one the user has, and nothing is ever typed into a password field.
    page = _SsoPage(
        {"input#user_name", "input#user_password", "button#sysverb_login"},
        "https://dev.example.com/login.do",
    )

    result = login._sso_sign_in(
        page, _state(), user="alice", locator=_LOCATOR, marker_path=str(tmp_path / "m.json")
    )

    assert page.visited == [_LOCATOR]
    assert _typed(page) == [("fill", _SSO_FIELD, "alice")]
    assert result["status"] == "sso_redirected"


def test_at_the_identity_provider_nothing_is_typed(tmp_path, _fast):
    page = _SsoPage({"input[type='password']"}, "https://idp.example.org/authorize")

    result = login._sso_sign_in(
        page, _state(), user="alice", locator=_LOCATOR, marker_path=str(tmp_path / "m.json")
    )

    assert result["status"] == "sso_at_idp"
    assert page.calls == [] and page.visited == []


def test_an_unknown_user_id_spends_the_attempt(tmp_path, _fast):
    page = _SsoPage({_SSO_FIELD, _SSO_SUBMIT}, _LOCATOR, outcome="error")
    marker = str(tmp_path / "login.json")

    result = login._sso_sign_in(page, _state(), user="nobody", locator=_LOCATOR, marker_path=marker)

    assert result["status"] == "sso_not_located"
    assert login.already_attempted(marker, _state()) is True


def test_a_locator_that_neither_moves_nor_complains_is_unverified_not_success(tmp_path, _fast):
    page = _SsoPage({_SSO_FIELD, _SSO_SUBMIT}, _LOCATOR, outcome="nothing")
    marker = str(tmp_path / "login.json")

    result = login._sso_sign_in(page, _state(), user="alice", locator=_LOCATOR, marker_path=marker)

    assert result["status"] == "sso_unverified"
    assert login.already_attempted(marker, _state()) is True


def test_a_signed_in_tab_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(login, "LOGIN_FORM_WAIT_S", 0.0)
    page = _SsoPage({"#header"}, "https://dev.example.com/now/nav/ui/home")

    result = login._sso_sign_in(
        page, _state(), user="alice", locator=_LOCATOR, marker_path=str(tmp_path / "m.json")
    )

    assert result["status"] == "no_login_form"
    assert page.calls == [] and page.visited == []


def test_a_locator_page_without_its_field_is_reported_not_guessed(tmp_path):
    class _NoField(_SsoPage):
        def goto(self, url, wait_until=None, timeout=None):
            self.visited.append(url)
            self.url = url
            self.known = set()

    page = _NoField({"input#user_password"}, "https://dev.example.com/login.do")

    result = login._sso_sign_in(
        page, _state(), user="alice", locator=_LOCATOR, marker_path=str(tmp_path / "m.json")
    )

    assert result["status"] == "sso_no_locator"
    assert _typed(page) == []


def test_a_spent_sso_window_is_not_driven_again(tmp_path, monkeypatch):
    path = str(tmp_path / "login.json")
    login.record_attempt(path, _state())
    monkeypatch.setattr(
        login,
        "require_playwright",
        lambda: (_ for _ in ()).throw(AssertionError("must not attach")),
    )

    result = login.auto_login(_state(), credentials=None, marker_path=path, sso=("alice", _LOCATOR))

    assert result == {"status": "already_attempted", "mode": "sso"}


@pytest.mark.parametrize(
    "result",
    [
        {"status": "sso_redirected", "user": "alice"},
        {"status": "sso_at_idp"},
        {"status": "sso_not_located", "user": "alice"},
        {"status": "sso_unverified", "user": "alice"},
        {"status": "sso_no_locator", "url": _LOCATOR},
        {"status": "already_attempted", "mode": "sso"},
        {"status": "filled", "user": "alice", "mode": "sso"},
    ],
)
def test_every_sso_outcome_says_something(result):
    note = login.describe(result)

    assert note
    assert "password in the config" not in note


# ---------------------------------------------------------------------------
# The MCP's own login window (AuthManager): SSO has no password, so the user ID
# must still go into the locator — it used to wait for both and fill nothing.
# ---------------------------------------------------------------------------


def test_sso_user_id_is_typed_and_submitted_on_the_locator():
    page = FakePage(known={_SSO_FIELD, _SSO_SUBMIT}, url=_LOCATOR)

    assert login.fill_sso_user_id(page, "alice", wait_ms=10) == "submitted"
    assert page.calls == [("fill", _SSO_FIELD, "alice"), ("click", _SSO_SUBMIT)]


def test_off_the_locator_nothing_is_typed():
    page = FakePage(
        known={"input#password", "input[type='password']"}, url="https://idp.example.com/"
    )

    assert login.fill_sso_user_id(page, "alice", wait_ms=10) == "no_sso_field"
    assert page.calls == []


def test_the_api_login_window_takes_the_sso_branch_without_a_password():
    import inspect

    from servicenow_mcp.auth.auth_manager import AuthManager

    src = inspect.getsource(AuthManager._login_with_browser_sync)
    sso_at = src.index('== "sso"')
    assert "fill_sso_user_id(page, username" in src[sso_at : sso_at + 600]
    assert sso_at < src.index("elif username and password:")
