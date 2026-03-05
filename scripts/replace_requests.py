#!/usr/bin/env python3
"""Script to replace requests calls with auth_manager.make_request() in tools directory."""

import re
from pathlib import Path

TOOLS_DIR = Path("/Users/jshsakura/Documents/workspace/mfa-servicenow-mcp/src/servicenow_mcp/tools")


def replace_requests_in_file(filepath: Path) -> bool:
    """Replace requests.* calls with auth_manager.make_request() in a file."""
    content = filepath.read_text()
    original = content

    # Pattern for requests.METHOD( with headers=auth_manager.get_headers()
    # Handles multi-line calls

    # requests.get(url, ..., headers=auth_manager.get_headers(), ...) -> auth_manager.make_request("GET", url, ...)
    for method in ["get", "post", "put", "patch", "delete"]:
        # Match patterns like:
        # requests.get(
        #     url,
        #     headers=auth_manager.get_headers(),
        #     ...
        # )

        # Simple pattern for single-line calls
        pattern = rf"requests\.{method}\(\s*([^,]+),\s*headers=auth_manager\.get_headers\(\),"
        replacement = rf'auth_manager.make_request("{method.upper()}", \1,'
        content = re.sub(pattern, replacement, content)

        # Pattern with headers not first arg
        pattern = rf"requests\.{method}\(\s*([^,]+),\s*params=([^,]+),\s*headers=auth_manager\.get_headers\(\),"
        replacement = rf'auth_manager.make_request("{method.upper()}", \1, params=\2,'
        content = re.sub(pattern, replacement, content)

        # Pattern with json=data
        pattern = rf"requests\.{method}\(\s*([^,]+),\s*json=([^,]+),\s*headers=auth_manager\.get_headers\(\),"
        replacement = rf'auth_manager.make_request("{method.upper()}", \1, json=\2,'
        content = re.sub(pattern, replacement, content)

    # Remove remaining headers=auth_manager.get_headers() in make_request calls
    # This handles cases where headers is in the middle of args
    content = re.sub(r",\s*headers=auth_manager\.get_headers\(\)", "", content)

    if content != original:
        filepath.write_text(content)
        return True
    return False


def main():
    """Main function."""
    count = 0
    for filepath in TOOLS_DIR.glob("*.py"):
        if filepath.name == "__init__.py":
            continue
        if replace_requests_in_file(filepath):
            print(f"Updated: {filepath.name}")
            count += 1
        else:
            print(f"No changes: {filepath.name}")

    print(f"\nTotal files updated: {count}")


if __name__ == "__main__":
    main()
