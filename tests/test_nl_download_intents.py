"""Tests for the download/export NL intent resolver.

Covers EN and KO phrasing for widget + app targets, structured clarification
when slots are missing, and a perf regression gate so the resolver stays
sub-millisecond per call.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.nl_download_intents import resolve_download_intent
from servicenow_mcp.tools.sn_api import NaturalLanguageParams, sn_nl
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _make_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


# ---------------------------------------------------------------------------
# resolve_download_intent — direct unit tests
# ---------------------------------------------------------------------------


class TestResolverNonIntent:
    """Inputs that are NOT download intents must return None."""

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "how many incidents are there",
            "list all p1 changes",
            "describe the incident table",
            "create a new problem",
            "show me INC0012345",
            # 'pull request' is unrelated to download intent here, but the verb
            # 'pull' alone (with no widget/app/scope context) still trips intent
            # detection. We test the unambiguous no-intent path here.
            "what fields does sys_user have",
            "스코프가 뭔지 설명해줘",  # KO 'describe scope', no download verb
        ],
    )
    def test_returns_none(self, text):
        assert resolve_download_intent(text) is None


class TestResolverWidgetEN:
    def test_quoted_widget_name(self):
        result = resolve_download_intent('download widget "my-widget"')
        assert result["needs_clarification"] is False
        assert result["target_type"] == "widget"
        assert result["tool"] == "download_portal_sources"
        assert result["params"] == {"widget_ids": ["my-widget"]}

    def test_widget_following_keyword(self):
        result = resolve_download_intent("download widget my_widget_id")
        assert result["needs_clarification"] is False
        assert result["params"]["widget_ids"] == ["my_widget_id"]

    def test_widget_preceding_keyword(self):
        result = resolve_download_intent("download the foo widget")
        assert result["needs_clarification"] is False
        assert result["params"]["widget_ids"] == ["foo"]

    def test_sys_id(self):
        sys_id = "abcdef0123456789abcdef0123456789"
        result = resolve_download_intent(f"export the widget {sys_id}")
        assert result["needs_clarification"] is False
        assert result["params"]["widget_ids"] == [sys_id]
        # 'export' verb echoed back
        assert result["intent"] == "export"

    def test_widget_with_scope(self):
        result = resolve_download_intent("download widget my-w in x_my_app")
        assert result["needs_clarification"] is False
        assert result["params"] == {"scope": "x_my_app", "widget_ids": ["my-w"]}

    def test_all_widgets_in_scope_routes_with_scope_only(self):
        result = resolve_download_intent("download all widgets in x_my_app")
        assert result["needs_clarification"] is False
        assert result["target_type"] == "widget"
        assert result["params"] == {"scope": "x_my_app"}
        assert "widget_ids" not in result["params"]

    def test_multiple_quoted_widgets(self):
        result = resolve_download_intent("export widgets 'foo', 'bar'")
        assert result["needs_clarification"] is False
        assert result["params"]["widget_ids"] == ["foo", "bar"]

    def test_widget_token_equal_to_scope_dropped(self):
        # 'download widget x_my_app' is ambiguous — treat as scope-only, not
        # as a widget literally named 'x_my_app'.
        result = resolve_download_intent("download widget x_my_app")
        assert result["needs_clarification"] is False
        assert result["params"] == {"scope": "x_my_app"}


class TestResolverWidgetKO:
    def test_widget_following_korean_keyword(self):
        result = resolve_download_intent("위젯 my_widget 다운로드")
        assert result["needs_clarification"] is False
        assert result["target_type"] == "widget"
        assert result["params"]["widget_ids"] == ["my_widget"]

    def test_korean_export_verb(self):
        result = resolve_download_intent("위젯 my_widget 내보내기")
        assert result["needs_clarification"] is False
        assert result["intent"] == "export"
        assert result["params"]["widget_ids"] == ["my_widget"]

    def test_korean_quoted_widget(self):
        result = resolve_download_intent("위젯 'my-widget' 받아줘")
        assert result["needs_clarification"] is False
        assert result["params"]["widget_ids"] == ["my-widget"]

    def test_korean_scope_widget(self):
        result = resolve_download_intent("x_my_app 위젯 다 받아줘")
        assert result["needs_clarification"] is False
        assert result["target_type"] == "widget"
        assert result["params"] == {"scope": "x_my_app"}


class TestResolverAppEN:
    def test_app_with_scope(self):
        result = resolve_download_intent("download app x_my_app")
        assert result["needs_clarification"] is False
        assert result["target_type"] == "app"
        assert result["tool"] == "download_app_sources"
        assert result["params"] == {"scope": "x_my_app"}

    def test_bare_scope_implies_app(self):
        result = resolve_download_intent("download x_my_app")
        assert result["needs_clarification"] is False
        assert result["target_type"] == "app"
        assert result["params"] == {"scope": "x_my_app"}

    def test_pull_all_sources_for_scope(self):
        result = resolve_download_intent("pull all sources for scope x_my_app")
        assert result["needs_clarification"] is False
        assert result["target_type"] == "app"
        assert result["params"] == {"scope": "x_my_app"}

    def test_export_alias(self):
        result = resolve_download_intent("export the whole app x_my_app")
        assert result["needs_clarification"] is False
        assert result["intent"] == "export"
        assert result["params"] == {"scope": "x_my_app"}


class TestResolverAppKO:
    def test_korean_app_with_scope(self):
        result = resolve_download_intent("앱 x_my_app 다운로드")
        assert result["needs_clarification"] is False
        assert result["target_type"] == "app"
        assert result["params"] == {"scope": "x_my_app"}

    def test_korean_scope_keyword(self):
        result = resolve_download_intent("스코프 x_my_app 전체 다운받기")
        assert result["needs_clarification"] is False
        assert result["target_type"] == "app"
        assert result["params"] == {"scope": "x_my_app"}


class TestResolverClarification:
    def test_app_missing_scope(self):
        result = resolve_download_intent("download the whole app")
        assert result["needs_clarification"] is True
        assert result["target_type"] == "app"
        assert result["missing"] == ["scope"]
        assert result["suggested_tool"] == "download_app_sources"

    def test_widget_missing_token(self):
        result = resolve_download_intent("download the widget")
        assert result["needs_clarification"] is True
        assert result["target_type"] == "widget"
        assert result["missing"] == ["widget_token"]
        assert result["suggested_tool"] == "download_portal_sources"

    def test_all_widgets_without_scope_asks_for_scope(self):
        # 'download all widgets' (no scope) — pulling every widget across the
        # whole instance is unsafe, so we ask for scope, not a widget name.
        result = resolve_download_intent("download all widgets")
        assert result["needs_clarification"] is True
        assert result["target_type"] == "widget"
        assert result["missing"] == ["scope"]

    def test_fully_ambiguous(self):
        result = resolve_download_intent("download it")
        assert result["needs_clarification"] is True
        assert result["target_type"] == "unknown"
        assert result["missing"] == ["target_type"]
        assert result["suggested_tool"] is None

    def test_korean_app_missing_scope(self):
        result = resolve_download_intent("앱 전체 다운로드해줘")
        assert result["needs_clarification"] is True
        assert result["target_type"] == "app"
        assert result["missing"] == ["scope"]


# ---------------------------------------------------------------------------
# sn_nl integration — resolver hand-off + legacy fallback
# ---------------------------------------------------------------------------


class TestSnNlDownloadHandoff:
    """sn_nl must forward download intents into the right execution tool."""

    def test_app_routes_to_download_app_sources(self):
        config = _make_config()
        auth = MagicMock()
        with patch("servicenow_mcp.tools.source_tools.download_app_sources") as mock_dl:
            mock_dl.return_value = {"success": True, "scope": "x_my_app"}
            result = sn_nl(config, auth, NaturalLanguageParams(text="download app x_my_app"))
        assert result["success"] is True
        mock_dl.assert_called_once()
        called_params = mock_dl.call_args.args[2]
        assert called_params.scope == "x_my_app"

    def test_widget_routes_to_download_portal_sources(self):
        config = _make_config()
        auth = MagicMock()
        with patch("servicenow_mcp.tools.portal_tools.download_portal_sources") as mock_dl:
            mock_dl.return_value = {"success": True}
            result = sn_nl(
                config,
                auth,
                NaturalLanguageParams(text='download widget "my-widget"'),
            )
        assert result["success"] is True
        mock_dl.assert_called_once()
        called_params = mock_dl.call_args.args[2]
        assert called_params.widget_ids == ["my-widget"]

    def test_clarification_does_not_call_any_tool(self):
        config = _make_config()
        auth = MagicMock()
        with (
            patch("servicenow_mcp.tools.source_tools.download_app_sources") as mock_app,
            patch("servicenow_mcp.tools.portal_tools.download_portal_sources") as mock_widget,
        ):
            result = sn_nl(config, auth, NaturalLanguageParams(text="download it"))
        assert result["needs_clarification"] is True
        assert result["executed"] is False
        mock_app.assert_not_called()
        mock_widget.assert_not_called()
        # No SN API call either
        auth.make_request.assert_not_called()

    def test_korean_widget_phrasing_routes(self):
        config = _make_config()
        auth = MagicMock()
        with patch("servicenow_mcp.tools.portal_tools.download_portal_sources") as mock_dl:
            mock_dl.return_value = {"success": True}
            result = sn_nl(
                config,
                auth,
                NaturalLanguageParams(text="위젯 my_widget 다운로드"),
            )
        assert result["success"] is True
        called_params = mock_dl.call_args.args[2]
        assert called_params.widget_ids == ["my_widget"]

    def test_korean_portal_source_routes_to_portal_not_app(self):
        """'전체 포털 소스' must route to download_portal_sources, not download_app_sources."""
        result = resolve_download_intent("x_my_app 스코프 전체 포털 소스를 다운로드 받자")
        assert result is not None
        assert result["needs_clarification"] is False
        assert result["tool"] == "download_portal_sources"
        assert result["params"]["scope"] == "x_my_app"

    def test_korean_portal_bare_routes_to_portal(self):
        """'포털 소스 다운로드' → download_portal_sources."""
        result = resolve_download_intent("x_my_app 포털 소스 다운로드")
        assert result is not None
        assert result["tool"] == "download_portal_sources"

    def test_en_portal_sources_routes_to_portal(self):
        """'download portal sources for x_my_app' → download_portal_sources."""
        result = resolve_download_intent("download portal sources for x_my_app")
        assert result is not None
        assert result["tool"] == "download_portal_sources"
        assert result["params"]["scope"] == "x_my_app"

    def test_jeonche_sose_still_routes_to_app(self):
        """'전체 소스' (without 포털) → download_app_sources, not portal."""
        result = resolve_download_intent("x_my_app 전체 소스 다운로드")
        assert result is not None
        assert result["tool"] == "download_app_sources"
        assert result["params"]["scope"] == "x_my_app"


# ---------------------------------------------------------------------------
# Defensive guards — false-positive phrases, oversized inputs, shape contract
# ---------------------------------------------------------------------------


class TestResolverFalsePositiveGuards:
    """Phrases that contain a download/export verb but mean something else
    must hand off to legacy sn_nl, not hijack the request."""

    @pytest.mark.parametrize(
        "text",
        [
            "review the pull request",
            "merge this pull request please",
            "the download speed is slow",
            "download bandwidth is throttled",
            "export to csv from incident table",
            "export the data as csv",
            "csv export of all changes",
            "data export for finance",
        ],
    )
    def test_known_false_positive_returns_none(self, text):
        assert resolve_download_intent(text) is None


class TestResolverInputCap:
    """Pathological inputs (giant pasted blobs) must not melt the resolver."""

    def test_oversized_input_still_resolves_quickly(self):
        # Intent in leading sentence, then a 50kB blob of junk.
        text = "download app x_my_app\n" + ("noise " * 10000)
        t0 = time.perf_counter()
        result = resolve_download_intent(text)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert result is not None
        assert result["target_type"] == "app"
        assert result["params"]["scope"] == "x_my_app"
        # Cap kicks in well before the 50kB tail is touched.
        assert elapsed_ms < 5, f"oversized input took {elapsed_ms:.2f}ms"

    def test_intent_keyword_after_cap_still_returns_none(self):
        # Verb buried after the 2k char cap → resolver doesn't see it,
        # legacy handler takes over.
        text = ("filler " * 400) + " download app x_my_app"
        assert len(text) > 2000
        assert resolve_download_intent(text) is None


class TestResolverResponseShape:
    """Lock the keys present in each response branch. Phase 2 expansion
    must not silently change this contract."""

    _READY_KEYS = {"intent", "target_type", "needs_clarification", "tool", "params"}
    _CLARIFY_KEYS = {
        "intent",
        "target_type",
        "needs_clarification",
        "missing",
        "question",
        "suggested_tool",
    }

    def test_ready_route_has_exact_keys(self):
        result = resolve_download_intent("download app x_my_app")
        assert set(result.keys()) == self._READY_KEYS
        assert result["intent"] in {"download", "export"}
        assert result["target_type"] in {"widget", "app"}
        assert isinstance(result["params"], dict)

    def test_clarification_has_exact_keys(self):
        result = resolve_download_intent("download the whole app")
        assert set(result.keys()) == self._CLARIFY_KEYS
        assert isinstance(result["missing"], list)
        assert len(result["missing"]) >= 1
        assert isinstance(result["question"], str) and result["question"]

    def test_unknown_target_clarification_has_no_suggested_tool(self):
        result = resolve_download_intent("download it")
        assert set(result.keys()) == self._CLARIFY_KEYS
        assert result["target_type"] == "unknown"
        assert result["suggested_tool"] is None


# ---------------------------------------------------------------------------
# Performance gate — resolver is the first hop on every NL call.
# ---------------------------------------------------------------------------


class TestResolverPerformance:
    def test_p99_under_1ms(self):
        """Resolver p99 must stay <1ms. Hard ceiling is 5ms to absorb CI noise."""
        samples = [
            "download widget my-widget",
            "download app x_my_app",
            "download it",
            "위젯 my_widget 다운로드",
            "show me p1 incidents",  # non-intent fast path
            "how many users are there",
            "pull all sources for scope x_my_app",
            "download all widgets in x_my_app",
        ]
        durations_us: list[float] = []
        # Warm caches and JIT branch predictors with a few iterations first.
        for _ in range(50):
            for s in samples:
                resolve_download_intent(s)
        for _ in range(2000):
            for s in samples:
                t0 = time.perf_counter()
                resolve_download_intent(s)
                durations_us.append((time.perf_counter() - t0) * 1_000_000)
        durations_us.sort()
        p99 = durations_us[int(len(durations_us) * 0.99)]
        # <1ms target, 5ms hard ceiling for noisy CI environments.
        assert p99 < 5_000, f"p99={p99:.1f}us exceeds 5ms ceiling"
