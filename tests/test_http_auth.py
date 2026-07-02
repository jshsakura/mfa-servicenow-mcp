"""HTTP transport auth policy tests."""

import pytest

from servicenow_mcp.utils.http_auth import (
    HttpAuthError,
    is_authorized,
    is_loopback_host,
    resolve_http_auth_token,
)


class TestIsLoopbackHost:
    def test_loopback_variants(self):
        for h in ("127.0.0.1", "::1", "localhost", "LOCALHOST", "", None):
            assert is_loopback_host(h) is True

    def test_non_loopback(self):
        for h in ("0.0.0.0", "::", "192.168.1.10", "myhost.internal"):
            assert is_loopback_host(h) is False


class TestResolveHttpAuthToken:
    def test_non_loopback_without_token_fails_closed(self):
        with pytest.raises(HttpAuthError, match="non-loopback"):
            resolve_http_auth_token("0.0.0.0", None)
        with pytest.raises(HttpAuthError):
            resolve_http_auth_token("192.168.1.5", "   ")  # whitespace == no token

    def test_loopback_without_token_is_allowed(self):
        assert resolve_http_auth_token("127.0.0.1", None) is None
        assert resolve_http_auth_token("localhost", "") is None

    def test_token_returned_and_trimmed(self):
        assert resolve_http_auth_token("0.0.0.0", "  secret  ") == "secret"

    def test_token_enforced_even_on_loopback(self):
        # Defence in depth: a token set on loopback is still returned (enforced).
        assert resolve_http_auth_token("127.0.0.1", "secret") == "secret"


class TestIsAuthorized:
    def test_valid_bearer(self):
        assert is_authorized("Bearer secret", "secret") is True
        assert is_authorized("bearer secret", "secret") is True  # scheme case-insensitive

    def test_wrong_token(self):
        assert is_authorized("Bearer nope", "secret") is False

    def test_missing_or_malformed(self):
        assert is_authorized(None, "secret") is False
        assert is_authorized("", "secret") is False
        assert is_authorized("secret", "secret") is False  # no scheme
        assert is_authorized("Basic secret", "secret") is False
        assert is_authorized("Bearer", "secret") is False

    def test_token_with_spaces_preserved(self):
        # Only the scheme is split off; the token itself is compared verbatim.
        assert is_authorized("Bearer a b c", "a b c") is True
