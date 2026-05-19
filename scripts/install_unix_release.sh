#!/usr/bin/env bash
set -euo pipefail

install_dir="${HOME}/.local/bin"

usage() {
  cat >&2 <<USAGE
Usage: ./install.sh [--install-dir <path>]

Copies the bundled servicenow-mcp executable to \$HOME/.local/bin
(or --install-dir) and, if a ms-playwright Chromium zip sits next to
this script, extracts it into the standard Playwright browser cache.

This script does NOT modify any MCP client config — paste the config
snippet from the README's "Local install" section into your client by
hand to avoid breaking existing entries.

Options:
  --install-dir <path>   Where to copy the executable (default: \$HOME/.local/bin)
  -h, --help             Show this help
USAGE
}

# Env-var fallback for backwards compatibility
install_dir="${INSTALL_DIR:-$install_dir}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) install_dir="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

bundle_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_bin="$bundle_dir/servicenow-mcp"
target_bin="$install_dir/servicenow-mcp"

if [[ ! -f "$source_bin" ]]; then
  echo "Error: $source_bin not found. Run this script from the extracted release zip." >&2
  exit 1
fi

mkdir -p "$install_dir"
cp "$source_bin" "$target_bin"
chmod +x "$target_bin"

case "$(uname -s)" in
  Darwin) browser_cache="$HOME/Library/Caches/ms-playwright" ;;
  *) browser_cache="$HOME/.cache/ms-playwright" ;;
esac

existing_chromium="$(find "$browser_cache" -maxdepth 1 -type d -name 'chromium-*' 2>/dev/null | head -n 1)"
if [[ -n "$existing_chromium" ]]; then
  echo "Chromium already installed at $existing_chromium — skipping bundled Chromium zip."
else
  browser_zip="$(find "$bundle_dir" -maxdepth 1 -type f -name 'ms-playwright*.zip' | head -n 1)"
  if [[ -n "$browser_zip" && -f "$browser_zip" ]]; then
    mkdir -p "$browser_cache"
    python3 - <<PY
import zipfile
from pathlib import Path
zipfile.ZipFile("$browser_zip").extractall(Path("$browser_cache"))
PY
    echo "Installed bundled Playwright Chromium cache to $browser_cache"
  else
    echo "Chromium not found at $browser_cache and no ms-playwright zip next to install.sh."
    echo "Place the matching ms-playwright zip next to install.sh and rerun if browser auth needs Chromium offline,"
    echo "or run 'playwright install chromium' on a host with internet access."
  fi
fi

echo
echo "Installed ServiceNow MCP:"
echo "  Server:  $target_bin"
echo
echo "Next: paste the MCP config snippet from the README 'Local install' section"
echo "      into your client's config file (e.g. .mcp.json / ~/.codex/config.toml / opencode.json)."
echo "      Set 'command' to: $target_bin"
echo "      Then restart your MCP client."
