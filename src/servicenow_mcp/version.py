"""Version utilities for the package.

The repository source of truth is `pyproject.toml` during development.
Installed package metadata is used as a fallback outside the source tree.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import tomllib


PACKAGE_NAME = "mfa-servicenow-mcp"


def _find_pyproject(start: Path) -> Path | None:
    for current in [start, *start.parents]:
        candidate = current / "pyproject.toml"
        if candidate.exists():
            return candidate
    return None


def get_version() -> str:
    pyproject_path = _find_pyproject(Path(__file__).resolve())
    if pyproject_path is not None:
        with pyproject_path.open("rb") as handle:
            data = tomllib.load(handle)
        project = data.get("project", {})
        pyproject_version = project.get("version")
        if isinstance(pyproject_version, str) and pyproject_version.strip():
            return pyproject_version.strip()

    try:
        return package_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.0"


__version__ = get_version()
