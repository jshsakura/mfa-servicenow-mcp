"""Build desktop release zips for the current OS.

The MCP executable and the Playwright browser cache are intentionally separate:

- servicenow-mcp-<platform>-<version>.zip contains the PyInstaller executable
  plus a small install script.
- ms-playwright-chromium-<platform>-<version>.zip is optional for locked-down
  networks where `python -m playwright install chromium` is blocked.

Build each platform on that platform so PyInstaller and Playwright produce the
right binary/browser payload.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read version from pyproject.toml")
    return match.group(1)


def _platform_tag() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64")
    if system == "darwin":
        system = "macos"
    if system not in {"windows", "macos", "linux"}:
        raise RuntimeError(f"Unsupported build platform: {platform.system()}")
    exe_name = "servicenow-mcp.exe" if system == "windows" else "servicenow-mcp"
    return f"{system}-{machine}", exe_name


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def _zip_dir(source_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir))


def _build_executable(bundle_dir: Path, exe_name: str) -> None:
    _run([sys.executable, "-m", "pip", "install", "-e", ".[browser]"])
    _run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--onefile",
            "--name",
            Path(exe_name).stem,
            "--collect-all",
            "servicenow_mcp",
            "--collect-all",
            "playwright",
            "--copy-metadata",
            "mfa-servicenow-mcp",
            "--copy-metadata",
            "playwright",
            "src/servicenow_mcp/cli.py",
        ]
    )
    pyinstaller_output = ROOT / "dist" / exe_name
    if not pyinstaller_output.exists() and exe_name == "servicenow-mcp.exe":
        pyinstaller_output = ROOT / "dist" / "servicenow-mcp.exe"
    if not pyinstaller_output.exists():
        pyinstaller_output = ROOT / "dist" / "servicenow-mcp"
    shutil.copy2(pyinstaller_output, bundle_dir / exe_name)


def _copy_install_script(bundle_dir: Path, platform_tag: str) -> None:
    if platform_tag.startswith("windows"):
        shutil.copy2(ROOT / "scripts" / "install_windows_release.ps1", bundle_dir / "install.ps1")
    else:
        target = bundle_dir / "install.sh"
        shutil.copy2(ROOT / "scripts" / "install_unix_release.sh", target)
        target.chmod(0o755)


def _build_browser_zip(output_dir: Path, platform_tag: str, version: str) -> Path:
    cache_dir = output_dir / f"ms-playwright-{platform_tag}-{version}"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(cache_dir)
    _run([sys.executable, "-m", "pip", "install", "-e", ".[browser]"])
    _run([sys.executable, "-m", "playwright", "install", "chromium"], env=env)
    zip_path = output_dir / f"ms-playwright-chromium-{platform_tag}-{version}.zip"
    _zip_dir(cache_dir, zip_path)
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build desktop release zip for current OS")
    parser.add_argument("--output-dir", default="dist/desktop")
    parser.add_argument(
        "--browser-zip",
        action="store_true",
        help="Also build a Playwright Chromium cache zip for blocked networks.",
    )
    args = parser.parse_args()

    version = _version()
    platform_tag, exe_name = _platform_tag()
    output_dir = (ROOT / args.output_dir).resolve()
    bundle_name = f"servicenow-mcp-{platform_tag}-{version}"
    bundle_dir = output_dir / bundle_name
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    _build_executable(bundle_dir, exe_name)
    _copy_install_script(bundle_dir, platform_tag)
    shutil.copy2(ROOT / "LICENSE", bundle_dir / "LICENSE")

    bundle_zip = output_dir / f"{bundle_name}.zip"
    _zip_dir(bundle_dir, bundle_zip)
    print(f"Created {bundle_zip}")

    if args.browser_zip:
        browser_zip = _build_browser_zip(output_dir, platform_tag, version)
        print(f"Created {browser_zip}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
