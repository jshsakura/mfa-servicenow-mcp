"""Unit tests for per-instance auth-type resolution.

Model: browser is the default; per-profile username/password select WHO (prefill
+ declared owner for G10), NEVER the auth type. The former creds-present → basic
auto-downgrade silently broke MFA/SSO instances the moment a profile declared
its owner — only an explicit ``auth_type`` changes the type now.
"""

from servicenow_mcp.utils.instances import resolve_auth_type


class TestResolveAuthType:
    def test_no_creds_keeps_browser_default(self):
        # Nothing entered → the global browser (headless) default stands.
        assert resolve_auth_type({"url": "https://x"}, "browser") == "browser"

    def test_username_password_does_not_change_auth_type(self):
        # Profile creds override WHO logs in, not HOW: browser stays browser
        # (MFA/SSO instances would break on a silent basic downgrade).
        entry = {"url": "https://prod", "username": "svc", "password": "pw"}
        assert resolve_auth_type(entry, "browser") == "browser"

    def test_explicit_basic_is_the_only_way_to_opt_out(self):
        entry = {"username": "svc", "password": "pw", "auth_type": "basic"}
        assert resolve_auth_type(entry, "browser") == "basic"

    def test_explicit_auth_type_always_wins(self):
        # Explicit browser keeps browser even with creds present (prefill/SSO).
        entry = {"username": "svc", "password": "pw", "auth_type": "browser"}
        assert resolve_auth_type(entry, "browser") == "browser"

    def test_explicit_auth_type_wins_over_default(self):
        assert resolve_auth_type({"auth_type": "oauth"}, "browser") == "oauth"

    def test_username_only_does_not_flip(self):
        # Half credentials must NOT change anything either.
        assert resolve_auth_type({"username": "svc"}, "browser") == "browser"
        assert resolve_auth_type({"password": "pw"}, "browser") == "browser"

    def test_non_browser_default_not_overridden_by_creds(self):
        assert resolve_auth_type({"username": "u", "password": "p"}, "oauth") == "oauth"
        assert resolve_auth_type({"username": "u", "password": "p"}, "basic") == "basic"

    def test_none_entry_returns_default(self):
        assert resolve_auth_type(None, "browser") == "browser"

    def test_case_insensitive(self):
        assert resolve_auth_type({"auth_type": "BASIC"}, "browser") == "basic"
        assert resolve_auth_type({"username": "u", "password": "p"}, "BROWSER") == "browser"


class TestResolveEnvReference:
    def test_resolves_placeholder(self, monkeypatch):
        from servicenow_mcp.utils.instances import resolve_env_reference

        monkeypatch.setenv("MY_SECRET", "s3cret")
        assert resolve_env_reference("${MY_SECRET}") == "s3cret"

    def test_literal_passthrough(self):
        from servicenow_mcp.utils.instances import resolve_env_reference

        assert resolve_env_reference("plain-password") == "plain-password"
        assert resolve_env_reference(None) is None

    def test_unset_env_returns_none(self, monkeypatch):
        from servicenow_mcp.utils.instances import resolve_env_reference

        monkeypatch.delenv("NOPE_NOT_SET", raising=False)
        assert resolve_env_reference("${NOPE_NOT_SET}") is None


class TestHasEnvReference:
    def test_detects_full_and_partial_references(self):
        from servicenow_mcp.utils.instances import has_env_reference

        assert has_env_reference("${VAR}") is True
        assert has_env_reference("${VAULT}_prod") is True  # partial — the trap
        assert has_env_reference("prefix${A}") is True
        assert has_env_reference("plain-password") is False
        assert has_env_reference(None) is False
        assert has_env_reference(123) is False


class TestAuthForInstanceEntryInheritance:
    """Named-profile credential inheritance: entry → active config → global env.

    A profile that writes nothing follows the globals; a profile with its own
    username/password overrides them (and stays on browser auth — creds pick
    WHO, not HOW).
    """

    def _fake_server(self, base_auth):
        from types import SimpleNamespace

        from servicenow_mcp.server import ServiceNowMCP

        fake = SimpleNamespace(config=SimpleNamespace(auth=base_auth))
        return lambda entry: ServiceNowMCP._auth_for_instance_entry(fake, entry)

    def _browser_base(self, username=None, password=None):
        from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig

        return AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(username=username, password=password),
        )

    def test_profile_without_creds_follows_global_env(self, monkeypatch):
        monkeypatch.setenv("SERVICENOW_USERNAME", "global_a")
        monkeypatch.setenv("SERVICENOW_PASSWORD", "global_pw")
        build = self._fake_server(self._browser_base())

        auth = build({"url": "https://dev.example.com"})

        assert auth.type.value == "browser"
        assert auth.browser.username == "global_a"
        assert auth.browser.password == "global_pw"

    def test_profile_creds_override_global(self, monkeypatch):
        monkeypatch.setenv("SERVICENOW_USERNAME", "global_a")
        monkeypatch.setenv("SERVICENOW_PASSWORD", "global_pw")
        build = self._fake_server(self._browser_base(username="global_a", password="global_pw"))

        auth = build({"url": "https://prod.example.com", "username": "prod_b", "password": "pw_b"})

        # WHO changes; HOW does not (browser stays browser — no basic downgrade).
        assert auth.type.value == "browser"
        assert auth.browser.username == "prod_b"
        assert auth.browser.password == "pw_b"

    def test_explicit_basic_without_creds_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("SERVICENOW_USERNAME", "global_a")
        monkeypatch.setenv("SERVICENOW_PASSWORD", "global_pw")
        build = self._fake_server(self._browser_base())

        auth = build({"url": "https://x.example.com", "auth_type": "basic"})

        assert auth.type.value == "basic"
        assert auth.basic.username == "global_a"
        assert auth.basic.password == "global_pw"

    def test_explicit_basic_with_no_creds_anywhere_raises(self, monkeypatch):
        import pytest

        monkeypatch.delenv("SERVICENOW_USERNAME", raising=False)
        monkeypatch.delenv("SERVICENOW_PASSWORD", raising=False)
        build = self._fake_server(self._browser_base())

        with pytest.raises(ValueError, match="username and password"):
            build({"url": "https://x.example.com", "auth_type": "basic"})


class TestPlaceholderCredential:
    def test_detects_unfilled_placeholders(self):
        from servicenow_mcp.utils.instances import looks_like_unfilled_placeholder

        assert looks_like_unfilled_placeholder("REPLACE_WITH_PROD_USERNAME") is True
        assert looks_like_unfilled_placeholder("replace_with_password") is True
        assert looks_like_unfilled_placeholder("your_username") is True
        assert looks_like_unfilled_placeholder("changeme") is True
        assert looks_like_unfilled_placeholder("real.user@corp.com") is False
        assert looks_like_unfilled_placeholder("") is False
        assert looks_like_unfilled_placeholder(None) is False

    def test_explicit_basic_placeholder_username_raises(self, monkeypatch):
        # #65/P3-2: an un-substituted template placeholder must fail fast, not
        # log in / create a profile named after the placeholder.
        import pytest

        from servicenow_mcp.server import _entry_cred

        with pytest.raises(ValueError, match="placeholder"):
            _entry_cred({"username": "REPLACE_WITH_PROD_USERNAME"}, "username", None, required=True)

    def test_optional_browser_placeholder_is_dropped(self):
        # Browser SSO creds are optional prefill: a placeholder there is warned
        # and dropped (returns None), never used to create a profile.
        from servicenow_mcp.server import _entry_cred

        assert (
            _entry_cred(
                {"password": "REPLACE_WITH_PROD_PASSWORD"}, "password", None, required=False
            )
            is None
        )
