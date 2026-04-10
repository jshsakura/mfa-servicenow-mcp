import json
from pathlib import Path

from servicenow_mcp import __version__
from servicenow_mcp.cli import _check_for_updates
from servicenow_mcp.version import get_version


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_runtime_version_matches_pyproject():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    version_line = next(
        line for line in pyproject_path.read_text().splitlines() if line.startswith("version = ")
    )
    pyproject_version = version_line.split("=", 1)[1].strip().strip('"')

    assert get_version() == pyproject_version
    assert __version__ == pyproject_version


def test_update_check_uses_runtime_version(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["timeout"] = timeout
        seen["url"] = req.full_url
        return _FakeResponse({"info": {"version": "9.9.9"}})

    warnings = []

    monkeypatch.setattr("servicenow_mcp.cli.__version__", "1.4.0")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("servicenow_mcp.cli.logger.warning", warnings.append)

    _check_for_updates()

    assert seen["timeout"] == 3
    assert seen["url"].endswith("/mfa-servicenow-mcp/json")
    assert warnings
    assert "current: 1.4.0" in warnings[0]
