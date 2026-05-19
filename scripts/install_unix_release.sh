#!/usr/bin/env bash
set -euo pipefail

client="opencode"
instance_url=""
auth_type="browser"
install_dir="${HOME}/.local/bin"
install_skills="false"

usage() {
  cat >&2 <<USAGE
Usage: ./install.sh --instance-url <url> [options]

Required:
  --instance-url <url>      ServiceNow instance URL (e.g. https://acme.service-now.com)

Optional:
  --client <name>           MCP client to configure (default: opencode)
                            Supported: claude-code claude-desktop cursor vscode-copilot
                                       opencode codex windsurf gemini zed antigravity
  --auth-type <type>        browser | basic | oauth | api_key (default: browser)
  --install-dir <path>      Where to copy the executable (default: \$HOME/.local/bin)
  --install-skills          Also install bundled skills for the client (default: skipped)
  -h, --help                Show this help

Env-var fallbacks (when the matching flag is not given):
  SERVICENOW_INSTANCE_URL, CLIENT, AUTH_TYPE, INSTALL_DIR
USAGE
}

# Env-var fallbacks (kept for backwards compatibility)
instance_url="${SERVICENOW_INSTANCE_URL:-$instance_url}"
client="${CLIENT:-$client}"
auth_type="${AUTH_TYPE:-$auth_type}"
install_dir="${INSTALL_DIR:-$install_dir}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client) client="$2"; shift 2 ;;
    --instance-url) instance_url="$2"; shift 2 ;;
    --auth-type) auth_type="$2"; shift 2 ;;
    --install-dir) install_dir="$2"; shift 2 ;;
    --install-skills) install_skills="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$instance_url" ]]; then
  echo "Error: --instance-url is required." >&2
  usage
  exit 1
fi

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
  echo "If browser auth fails, place the matching ms-playwright zip next to install.sh and rerun, or run 'playwright install chromium' on a host with internet access."
fi

setup_args=(
  setup "$client"
  --server-command "$target_bin"
  --instance-url "$instance_url"
  --auth-type "$auth_type"
  --skip-chromium
)
if [[ "$install_skills" != "true" ]]; then
  setup_args+=(--skip-skills)
fi

"$target_bin" "${setup_args[@]}"

echo
echo "Installed ServiceNow MCP:"
echo "  Server: $target_bin"
echo "Restart your MCP client so it loads the updated config."
