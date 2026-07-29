"""Shared pytest fixtures for ServiceNow MCP tests.

Provides common mock objects (config, auth_manager, mock_response) used across
40+ test files, eliminating per-file boilerplate.
"""

import json
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

# ---------------------------------------------------------------------------
# Autouse: clear query cache between tests to prevent cross-test pollution
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_query_cache():
    """Clear sn_api query cache + Batch API availability verdicts between tests."""
    from servicenow_mcp.tools.sn_batch import reset_batch_support_cache

    invalidate_query_cache()
    reset_batch_support_cache()
    yield
    invalidate_query_cache()
    reset_batch_support_cache()


@pytest.fixture(autouse=True)
def _isolate_workspace_roots(tmp_path, monkeypatch):
    """Redirect the download-root auto-registry to a per-test file.

    Download tests exercise _resolve_scope_root / download_portal_sources,
    which record roots — without this they would write to the REAL user state
    (~/.mfa_servicenow_mcp/download_roots.json) and leak tmp paths into it.
    """
    from servicenow_mcp.utils import workspace_roots

    state = tmp_path / "_workspace_roots_state" / "download_roots.json"
    monkeypatch.setattr(workspace_roots, "_state_file", lambda: state)


@pytest.fixture(autouse=True)
def _isolate_write_journal(tmp_path, monkeypatch):
    """Redirect the write journal to a per-test dir — confirmed-write tests
    must never append to the REAL ~/.mfa_servicenow_mcp/write_journal/."""
    from servicenow_mcp.utils import write_journal

    monkeypatch.setattr(write_journal, "_journal_dir", lambda: tmp_path / "_write_journal")


@pytest.fixture(autouse=True)
def _isolate_auth_cache(tmp_path, monkeypatch, request):
    """Redirect the auth cache root — session JSON, login locks, Chromium
    profiles — to a per-test dir.

    Without this every AuthManager built in a test resolves the REAL
    ``~/.mfa_servicenow_mcp/``, which costs three separate things:

    - **Cross-test leakage.** A manager that saves a session leaves a file the
      NEXT test's manager adopts through ``_maybe_adopt_sibling_session_update``
      (a fresh manager starts at mtime 0, so any file on disk reads as a newer
      sibling write). Tests then fail on the previous test's cookies, and only
      in combination — each one passes alone, which is the worst way for a
      suite to break.
    - **Writes into the user's real state.** Fixture instances are fake, but
      ``session_example_service-now_com.json`` lands beside the real ones.
    - **Real browsers.** Anything that escapes its Playwright mocks launches
      Chromium into a profile under this root and navigates to the fixture
      URL — and ``example.service-now.com`` resolves, so that is a live page
      load on someone else's instance from a unit test run.

    Autouse, because the tests that need this are exactly the ones that would
    not think to ask for it. Tests OF the resolver itself opt out with
    ``@pytest.mark.real_cache_dir`` — they patch ``Path.home`` and assert on
    what ``_get_cache_dir`` returns, so stubbing it would test the stub.
    """
    if request.node.get_closest_marker("real_cache_dir"):
        return

    real = AuthManager._get_cache_dir

    def _cache_dir(self):
        # Only the HOME-derived default is redirected. A test that configures
        # user_data_dir is saying where the cache goes, and several assert on
        # exactly that — swallowing the configured branch here would break them
        # and, worse, would stop testing the resolver people actually override.
        if self.config.browser and self.config.browser.user_data_dir:
            return real(self)
        return str(tmp_path / "_auth_cache")

    monkeypatch.setattr(AuthManager, "_get_cache_dir", _cache_dir)


# ---------------------------------------------------------------------------
# Reusable fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_config() -> ServerConfig:
    """A valid ServerConfig with basic auth for unit tests."""
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def mock_auth(mock_config) -> MagicMock:
    """A MagicMock specced to AuthManager with basic-auth headers."""
    auth = MagicMock(spec=AuthManager)
    auth.get_headers.return_value = {
        "Authorization": "Basic YWRtaW46cGFzc3dvcmQ=",
        "Content-Type": "application/json",
    }
    return auth


# ---------------------------------------------------------------------------
# Helper function (importable, not a fixture)
# ---------------------------------------------------------------------------


def make_mock_response(data, *, status_code=200, headers=None):
    """Create a mock ``requests.Response``-like object.

    Importable helper for tests that need to build responses inline:

        from conftest import make_mock_response
    """
    mock = MagicMock()
    mock.json.return_value = data
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    mock.content = json.dumps(data).encode("utf-8")
    mock.headers = headers or {}
    return mock
