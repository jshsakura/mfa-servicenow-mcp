#!/usr/bin/env bash
set -euo pipefail

client="${CLIENT:-opencode}"
instance_url="${SERVICENOW_INSTANCE_URL:-}"
install_dir="${INSTALL_DIR:-$HOME/.local/bin}"

if [[ -z "$instance_url" ]]; then
  echo "Set SERVICENOW_INSTANCE_URL before running install.sh" >&2
  echo "Example: SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com ./install.sh" >&2
  exit 1
fi

bundle_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_bin="$bundle_dir/servicenow-mcp"
target_bin="$install_dir/servicenow-mcp"

mkdir -p "$install_dir"
cp "$source_bin" "$target_bin"
chmod +x "$target_bin"

browser_zip="$(find "$bundle_dir" -maxdepth 1 -type f -name 'ms-playwright*.zip' | head -n 1)"
if [[ -n "$browser_zip" && -f "$browser_zip" ]]; then
  case "$(uname -s)" in
    Darwin) browser_cache="$HOME/Library/Caches/ms-playwright" ;;
    *) browser_cache="$HOME/.cache/ms-playwright" ;;
  esac
  mkdir -p "$browser_cache"
  python3 - <<PY
import zipfile
from pathlib import Path
zipfile.ZipFile("$browser_zip").extractall(Path("$browser_cache"))
PY
  echo "Installed bundled Playwright Chromium cache to $browser_cache"
else
  echo "No ms-playwright browser zip found next to install.sh."
  echo "If browser auth fails, install Chromium with Playwright or place the release ms-playwright zip next to install.sh and run again."
fi

"$target_bin" setup "$client" \
  --server-command "$target_bin" \
  --instance-url "$instance_url" \
  --auth-type browser \
  --skip-chromium \
  --skip-skills

echo
echo "Installed ServiceNow MCP:"
echo "  Server: $target_bin"
echo "Restart your MCP client so it loads the updated config."
