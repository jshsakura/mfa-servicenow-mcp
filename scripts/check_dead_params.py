#!/usr/bin/env python
"""CI gate: flag Pydantic tool parameters that are declared but never used.

A param a tool accepts but never reads is a confusion trap — the LLM (or a
human) passes it expecting an effect that never happens. The
``approve_change.approver_id`` field was exactly this for a long time: declared,
documented, and silently ignored.

Heuristic: for each registered tool, take its params model's fields and check
the tool's defining module source for a reference to each field, via either:
  * attribute access ``.field`` (``params.field`` / ``p.field`` / ``self.field``)
  * a string literal ``"field"`` / ``'field'`` (getattr-forwarded field tuples,
    e.g. ``_project_change(params, _CHANGE_CREATE_FIELDS)``)

If neither appears anywhere in the module, the field is reported as dead.

False-positive policy: a field genuinely consumed in a way this heuristic can't
see (resolved dynamically, used only in a sibling module) goes on ALLOWLIST
below with a one-line justification. Keep it tight — prefer wiring or removing
the param over allowlisting it.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (tool_name, field) pairs that are declared-but-unreferenced for a legitimate
# reason. Add only after confirming the param is intentional. Format: comment +
# entry.
ALLOWLIST: set[tuple[str, str]] = set()


def load_tools() -> dict:
    src_path = REPO_ROOT / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    from servicenow_mcp.utils.registry import discover_tools

    return discover_tools()


def _module_source(func) -> str | None:
    try:
        path = inspect.getsourcefile(func)
    except TypeError:
        return None
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def _is_referenced(field: str, src: str) -> bool:
    esc = re.escape(field)
    # Attribute access (.field) OR exact string-literal forwarding ("field").
    return bool(re.search(rf"\.{esc}\b", src) or re.search(rf"""['"]{esc}['"]""", src))


def find_dead_params() -> list[tuple[str, str]]:
    tools = load_tools()
    dead: list[tuple[str, str]] = []
    for name, entry in sorted(tools.items()):
        func, params_model = entry[0], entry[1]
        fields = getattr(params_model, "model_fields", None)
        if not fields:
            continue
        src = _module_source(func)
        if src is None:
            continue
        for field in fields:
            if (name, field) in ALLOWLIST:
                continue
            if not _is_referenced(field, src):
                dead.append((name, field))
    return dead


def main() -> int:
    dead = find_dead_params()
    tools = load_tools()
    if not dead:
        print(f"OK: no dead tool parameters found ({len(tools)} tools scanned).")
        return 0

    print(f"FAIL: {len(dead)} declared-but-unused tool parameter(s):\n")
    for tool, field in dead:
        print(f"  - {tool}.{field}")
    print(
        "\nAction: wire the parameter into the tool's logic, remove it, or add "
        "(tool, field) to ALLOWLIST in this script with a justification."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
