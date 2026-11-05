"""state_dir resolver: registered > env > home default; matches AuthManager."""

import importlib
from pathlib import Path

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils import deploy_ledger, state_dir, workspace_roots, write_journal
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig

ENV = "SERVICENOW_BROWSER_USER_DATA_DIR"


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    state_dir.register_state_dir(None)
    yield
    state_dir.register_state_dir(None)


def test_default_is_home(tmp_path):
    assert state_dir.state_dir() == tmp_path / "home" / ".mfa_servicenow_mcp"


def test_env_beats_default(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, str(tmp_path / "env"))
    assert state_dir.state_dir() == tmp_path / "env"


def test_registered_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, str(tmp_path / "env"))
    state_dir.register_state_dir(str(tmp_path / "projA"))
    assert state_dir.state_dir() == tmp_path / "projA"


def _paths():
    # conftest stubs these helpers for isolation; reload to get the real ones.
    for mod in (workspace_roots, deploy_ledger, write_journal):
        importlib.reload(mod)
    return (
        workspace_roots._state_file(),
        deploy_ledger._state_file(),
        write_journal._journal_dir(),
    )


def test_helpers_follow_registered(tmp_path):
    state_dir.register_state_dir(str(tmp_path / "projA"))
    a, b, c = _paths()
    assert a == tmp_path / "projA" / "download_roots.json"
    assert b == tmp_path / "projA" / "xml_dirs.json"
    assert c == tmp_path / "projA" / "write_journal"


def test_helpers_follow_env(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, str(tmp_path / "env"))
    assert all(p.is_relative_to(tmp_path / "env") for p in _paths())


def test_helpers_default(tmp_path):
    assert all(p.is_relative_to(tmp_path / "home" / ".mfa_servicenow_mcp") for p in _paths())


def test_matches_auth_manager_cache_dir(tmp_path):
    x = tmp_path / "projB"
    cfg = AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig(user_data_dir=str(x)))
    am = AuthManager(cfg, "https://test.service-now.com")
    state_dir.register_state_dir(cfg.browser.user_data_dir)
    assert str(state_dir.state_dir()) == am._get_cache_dir()
