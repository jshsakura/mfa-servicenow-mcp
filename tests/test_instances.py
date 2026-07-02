"""Unit tests for per-instance auth-type resolution (browser opt-out)."""

from servicenow_mcp.utils.instances import resolve_auth_type


class TestResolveAuthType:
    def test_no_creds_keeps_browser_default(self):
        # Nothing entered → the global browser (headless) default stands.
        assert resolve_auth_type({"url": "https://x"}, "browser") == "browser"

    def test_username_password_opts_out_of_browser_to_basic(self):
        # An instance that brings its own creds uses basic — no browser window,
        # no need to also spell out auth_type. The "temp prod user" case.
        entry = {"url": "https://prod", "username": "svc", "password": "pw"}
        assert resolve_auth_type(entry, "browser") == "basic"

    def test_explicit_auth_type_always_wins(self):
        # Explicit browser keeps browser even with creds present (prefill/SSO).
        entry = {"username": "svc", "password": "pw", "auth_type": "browser"}
        assert resolve_auth_type(entry, "browser") == "browser"

    def test_explicit_auth_type_wins_over_default(self):
        assert resolve_auth_type({"auth_type": "oauth"}, "browser") == "oauth"

    def test_username_only_does_not_flip(self):
        # Half credentials must NOT silently pick basic (would mix with the
        # global password). Stays on the browser default.
        assert resolve_auth_type({"username": "svc"}, "browser") == "browser"
        assert resolve_auth_type({"password": "pw"}, "browser") == "browser"

    def test_non_browser_default_not_overridden_by_creds(self):
        # The opt-out only applies when the default is browser; a basic/oauth
        # default is left alone (creds there are expected).
        assert resolve_auth_type({"username": "u", "password": "p"}, "oauth") == "oauth"
        assert resolve_auth_type({"username": "u", "password": "p"}, "basic") == "basic"

    def test_none_entry_returns_default(self):
        assert resolve_auth_type(None, "browser") == "browser"

    def test_case_insensitive(self):
        assert resolve_auth_type({"auth_type": "BASIC"}, "browser") == "basic"
        assert resolve_auth_type({"username": "u", "password": "p"}, "BROWSER") == "basic"
