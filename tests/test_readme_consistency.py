"""Cross-language doc consistency.

Prose gets translated; commands do not. The install commands, the MCP client
`command`/`args` pairs, and the env var names must be byte-identical in every
localized README, because a reader copies them verbatim.

This exists because a real bug shipped without it: the Korean README's "if you
installed with pip, swap these" snippet showed the *uvx* values, so the one
group of readers who had already hit a uvx failure was pointed straight back at
uvx. Two reviewers caught it by eye. No test did.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

READMES = [
    "README.md",
    "README.ko.md",
    "README.ja.md",
    "README.zh.md",
    "README.es.md",
    "README.hi.md",
]

# Copy-paste surfaces. Identical across languages, no exceptions.
CANONICAL_STRINGS = {
    "uvx command": '"command": "uvx"',
    "uvx args": '"args": ["--with", "playwright", "--from", "mfa-servicenow-mcp", "servicenow-mcp"]',
    "pip command": '"command": "python"',
    "pip args": '"args": ["-m", "servicenow_mcp"]',
    "pip install": "pip install mfa-servicenow-mcp playwright",
    "server name env": "SERVICENOW_MCP_SERVER_NAME",
}


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("readme", READMES)
@pytest.mark.parametrize("label,text", sorted(CANONICAL_STRINGS.items()))
def test_canonical_command_present(readme: str, label: str, text: str):
    assert text in _read(readme), f"{readme} is missing the canonical {label}: {text}"


@pytest.mark.parametrize("readme", READMES)
def test_no_console_script_as_mcp_command(readme: str):
    """`servicenow-mcp` as an MCP `command` is an unsigned pip-generated .exe
    shim. Windows Smart App Control blocks it, which is the failure the pip
    path exists to avoid — so it must never be the documented invocation."""
    content = _read(readme)
    for bad in ('"command": "servicenow-mcp"', 'command = "servicenow-mcp"'):
        assert bad not in content, (
            f"{readme} configures the MCP server via the console script ({bad}). "
            "Use python -m servicenow_mcp instead — the shim is SAC-blocked."
        )


@pytest.mark.parametrize("readme", READMES)
def test_pip_swap_snippet_does_not_show_uvx(readme: str):
    """The "installed with pip? use these instead" snippet must show the pip
    values. Showing uvx there sends the blocked reader back to what blocked
    them — the exact bug this module was written for."""
    content = _read(readme)
    marker = '"command": "python"'
    assert marker in content, f"{readme} never shows the pip command form"

    # Every pip command line must be followed by pip args, not uvx args.
    for idx, line in enumerate(lines := content.splitlines()):
        if line.strip().startswith(marker):
            following = "\n".join(lines[idx + 1 : idx + 3])
            assert "servicenow_mcp" in following, (
                f"{readme}:{idx + 1} declares the pip command but the args that "
                f"follow are not the pip args:\n{following}"
            )
