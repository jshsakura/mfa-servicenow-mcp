"""Tests for servicenow_mcp.version — covering fallback paths."""

from unittest.mock import patch

from servicenow_mcp.version import _find_pyproject, get_version


def test_find_pyproject_returns_none_when_missing(tmp_path):
    """_find_pyproject returns None when no pyproject.toml exists in ancestors."""
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    result = _find_pyproject(deep)
    assert result is None


def test_get_version_falls_back_to_package_metadata():
    """When pyproject.toml is not found, falls back to importlib.metadata."""
    with patch("servicenow_mcp.version._find_pyproject", return_value=None):
        with patch("servicenow_mcp.version.package_version", return_value="1.2.3"):
            assert get_version() == "1.2.3"


def test_get_version_falls_back_to_000():
    """When both pyproject.toml and package metadata fail, returns 0.0.0."""
    from importlib.metadata import PackageNotFoundError

    with patch("servicenow_mcp.version._find_pyproject", return_value=None):
        with patch(
            "servicenow_mcp.version.package_version",
            side_effect=PackageNotFoundError("not installed"),
        ):
            assert get_version() == "0.0.0"


def test_get_version_ignores_empty_pyproject_version(tmp_path):
    """When pyproject.toml has empty/whitespace version, falls back."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "  "\n')
    with patch("servicenow_mcp.version._find_pyproject", return_value=pyproject):
        with patch("servicenow_mcp.version.package_version", return_value="4.5.6"):
            assert get_version() == "4.5.6"


def test_get_version_ignores_missing_version_key(tmp_path):
    """When pyproject.toml has no version key, falls back."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')
    with patch("servicenow_mcp.version._find_pyproject", return_value=pyproject):
        with patch("servicenow_mcp.version.package_version", return_value="7.8.9"):
            assert get_version() == "7.8.9"
