"""Cross-origin redirect credential-stripping (issue #63 batch 2 part 2/2).

The auth session must follow redirects (so logout/session-death detection via
response.history keeps working) but MUST NOT re-send Cookie/X-UserToken/api-key
headers to a different origin.
"""

from unittest.mock import MagicMock

from servicenow_mcp.auth.auth_manager import (
    _CROSS_ORIGIN_STRIP_HEADERS,
    _SafeRedirectSession,
    _same_origin,
    _strip_sensitive_headers,
)


class TestSameOrigin:
    def test_same_host_variants(self):
        assert _same_origin("https://x.service-now.com/a", "https://x.service-now.com/b")
        assert _same_origin("https://x.service-now.com", "https://x.service-now.com:443/y")
        assert _same_origin("https://x.service-now.com/a", "/relative/path")  # relative

    def test_cross_host(self):
        assert not _same_origin("https://x.service-now.com/a", "https://evil.com/a")
        assert not _same_origin("https://x.service-now.com/a", "http://x.service-now.com/a")
        assert not _same_origin("https://x.service-now.com/a", "https://x.service-now.com:8443/a")


class TestStripSensitiveHeaders:
    def test_removes_credentials_case_insensitive(self):
        h = {"Cookie": "c", "X-UserToken": "t", "Authorization": "a", "Accept": "json"}
        out = _strip_sensitive_headers(h, set())
        assert out == {"Accept": "json"}

    def test_extra_sensitive(self):
        h = {"X-Sn-Apikey": "k", "Accept": "json"}
        out = _strip_sensitive_headers(h, {"x-sn-apikey"})
        assert out == {"Accept": "json"}

    def test_none_passthrough(self):
        assert _strip_sensitive_headers(None, set()) is None


def _resp(status, location=None, url="https://x.service-now.com/api"):
    r = MagicMock()
    r.status_code = status
    r.headers = {"Location": location} if location else {}
    r.url = url
    return r


class TestSafeRedirectSessionRequest:
    def test_no_redirect_is_single_passthrough_call(self):
        # Healthy 200 → exactly one underlying call, unchanged kwargs, empty history.
        inner = MagicMock()
        inner.request.return_value = _resp(200)
        sess = _SafeRedirectSession(inner)
        headers = {"Cookie": "c", "X-UserToken": "t"}
        out = sess.request("GET", "https://x.service-now.com/api", headers=headers)
        assert out.status_code == 200
        assert inner.request.call_count == 1
        # allow_redirects forced False internally; original creds untouched.
        _, kw = inner.request.call_args
        assert kw["allow_redirects"] is False
        assert kw["headers"] == {"Cookie": "c", "X-UserToken": "t"}
        assert out.history == []

    def test_same_origin_redirect_keeps_credentials_and_builds_history(self):
        # 302 -> login.do on the SAME host (session death): creds preserved
        # (byte-identical to auto-follow), and history is populated so the
        # existing logout detection still fires.
        inner = MagicMock()
        inner.request.side_effect = [
            _resp(302, location="https://x.service-now.com/login.do"),
            _resp(200, url="https://x.service-now.com/login.do"),
        ]
        sess = _SafeRedirectSession(inner)
        out = sess.request("GET", "https://x.service-now.com/api", headers={"Cookie": "c"})
        assert out.status_code == 200
        assert len(out.history) == 1
        # Second hop still carried the cookie (same origin).
        second_kwargs = inner.request.call_args_list[1].kwargs
        assert second_kwargs["headers"] == {"Cookie": "c"}

    def test_cross_origin_redirect_strips_credentials(self):
        inner = MagicMock()
        inner.request.side_effect = [
            _resp(302, location="https://evil.example.com/steal"),
            _resp(200, url="https://evil.example.com/steal"),
        ]
        sess = _SafeRedirectSession(inner)
        sess.register_sensitive_header("X-Sn-Apikey")
        out = sess.request(
            "GET",
            "https://x.service-now.com/api",
            headers={"Cookie": "c", "X-UserToken": "t", "X-Sn-Apikey": "k", "Accept": "json"},
        )
        assert out.status_code == 200
        # The hop to evil.com carried NONE of the credentials.
        second_kwargs = inner.request.call_args_list[1].kwargs
        assert second_kwargs["headers"] == {"Accept": "json"}
        assert "cookies" not in second_kwargs or not second_kwargs.get("cookies")

    def test_allow_redirects_false_is_respected(self):
        inner = MagicMock()
        inner.request.return_value = _resp(302, location="https://x.service-now.com/login.do")
        sess = _SafeRedirectSession(inner)
        out = sess.request("GET", "https://x.service-now.com/api", allow_redirects=False)
        assert out.status_code == 302
        assert inner.request.call_count == 1  # not followed

    def test_redirect_cap_stops_the_loop(self):
        inner = MagicMock()
        inner.request.return_value = _resp(302, location="https://x.service-now.com/loop")
        sess = _SafeRedirectSession(inner)
        out = sess.request("GET", "https://x.service-now.com/api")
        assert out.status_code == 302
        assert inner.request.call_count == 11  # 1 + _MAX_MANUAL_REDIRECTS

    def test_delegates_unknown_attrs(self):
        inner = MagicMock()
        inner.headers = {"h": 1}
        sess = _SafeRedirectSession(inner)
        assert sess.headers == {"h": 1}
        sess.close()
        inner.close.assert_called_once()

    def test_cross_origin_strip_set_contents(self):
        assert {
            "cookie",
            "authorization",
            "x-usertoken",
            "x-csrf-token",
        } <= _CROSS_ORIGIN_STRIP_HEADERS

    def test_get_and_post_route_through_wrapper_request(self):
        # Regression: verb helpers MUST call THIS wrapper's request (like
        # requests.Session) so redirect safety applies and so a test patch of
        # .request also intercepts .get/.post. The probe uses .get, OAuth .post.
        inner = MagicMock()
        inner.request.return_value = _resp(200)
        sess = _SafeRedirectSession(inner)
        sess.request = MagicMock(return_value=_resp(200))  # patch the wrapper's request

        sess.get("https://x.service-now.com/probe", allow_redirects=False)
        sess.post("https://x.service-now.com/oauth_token.do", data={"a": 1})

        assert sess.request.call_count == 2
        assert sess.request.call_args_list[0].args[0] == "GET"
        assert sess.request.call_args_list[1].args[0] == "POST"
        # inner.request never called directly — everything funnels through wrapper.
        inner.request.assert_not_called()
