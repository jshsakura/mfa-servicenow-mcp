#!/usr/bin/env python3
"""Script to replace requests calls with auth_manager.make_request() - Pattern 2."""

import re
from pathlib import Path

TOOLS_DIR = Path("/Users/jshsakura/Documents/workspace/mfa-servicenow-mcp/src/servicenow_mcp/tools")


def replace_requests_pattern2(filepath: Path) -> bool:
    """Replace requests.* calls where headers is assigned separately."""
    content = filepath.read_text()
    original = content

    # Pattern: headers = auth_manager.get_headers() followed by requests.METHOD
    # Remove the headers assignment and add to make_request

    # Remove standalone headers = auth_manager.get_headers() lines
    content = re.sub(r"\s*headers = auth_manager\.get_headers\(\)\s*\n", "\n", content)

    # Remove headers = _get_headers(...) lines
    content = re.sub(r"\s*headers = _get_headers\([^)]+\)\s*\n", "\n", content)

    # Also handle headers = _get_headers(...) without newline issues
    content = re.sub(r"\s*headers = _get_headers\([^)]+\)", "", content)

    # Remove headers["Accept"] = ... and headers["Content-Type"] = ... assignments
    # These are handled by make_request internally
    content = re.sub(r'\s*headers\["Accept"\] = "[^"]+"\s*\n', "", content)
    content = re.sub(r'\s*headers\["Content-Type"\] = "[^"]+"\s*\n', "", content)
    content = re.sub(r"\s*headers\[\'Accept\'\] = \'[^\']+\'\s*\n", "", content)
    content = re.sub(r"\s*headers\[\'Content-Type\'\] = \'[^\']+\'\s*\n", "", content)

    # Also handle headers = auth_manager.get_headers() inline patterns
    content = re.sub(r"\s*headers = auth_manager\.get_headers\(\)", "", content)

    # Now replace requests.METHOD( with auth_manager.make_request
    for method in ["get", "post", "put", "patch", "delete"]:
        # requests.get(url, params=..., timeout=...) -> auth_manager.make_request("GET", url, params=..., timeout=...)
        pattern = rf"requests\.{method}\(\s*"
        replacement = rf'auth_manager.make_request("{method.upper()}", '
        content = re.sub(pattern, replacement, content)

    # Remove remaining headers=headers references (in make_request calls)
    content = re.sub(r",?\s*headers=headers", "", content)

    # Clean up any double commas
    content = re.sub(r",\s*,", ",", content)
    content = re.sub(r"\(\s*,", "(", content)

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
        if replace_requests_pattern2(filepath):
            print(f"Updated: {filepath.name}")
            count += 1
        else:
            print(f"No changes: {filepath.name}")

    print(f"\nTotal files updated: {count}")


if __name__ == "__main__":
    main()
