"""Policy layer for MCP server — write guards, safety checks.

The policies run *between* the package/action allowlist check and the
confirm gate in `_call_tool_impl`. Each guard is independent and raises
`PolicyViolation` (a ValueError subclass) to abort the call with a
LLM-readable message.
"""

from .write_guards import (
    PolicyViolation,
    run_concurrent_edit_guards,
    run_write_guards,
    strip_guard_fields,
)

__all__ = [
    "PolicyViolation",
    "run_concurrent_edit_guards",
    "run_write_guards",
    "strip_guard_fields",
]
