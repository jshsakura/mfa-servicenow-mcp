"""Tests for servicenow_mcp.utils.json_fast — stdlib json fallback path.

In this environment orjson is NOT installed, so json_fast uses the stdlib
fallback. We test the actual active path plus verify the orjson branch via
subprocess to avoid polluting module state.
"""

import subprocess
import sys

from servicenow_mcp.utils import json_fast

# ---------------------------------------------------------------------------
# Stdlib fallback (active in this environment)
# ---------------------------------------------------------------------------


def test_stdlib_backend_active():
    """The active backend should be stdlib json (orjson not installed)."""
    assert json_fast.BACKEND == "json"


def test_stdlib_loads():
    data = json_fast.loads('{"key": "value"}')
    assert data == {"key": "value"}


def test_stdlib_loads_bytes():
    data = json_fast.loads(b'{"num": 42}')
    assert data == {"num": 42}


def test_stdlib_dumps():
    result = json_fast.dumps({"a": 1})
    assert isinstance(result, str)
    # Compact separators: no spaces
    assert ": " not in result
    assert ", " not in result


def test_stdlib_dumps_non_ascii():
    """ensure_ascii=False should preserve unicode."""
    result = json_fast.dumps({"name": "\ud55c\uae00"})
    assert "\ud55c\uae00" in result


# ---------------------------------------------------------------------------
# Simulate orjson being available (isolated in subprocess)
# ---------------------------------------------------------------------------


def test_orjson_branch_when_available():
    """Verify the orjson branch works by running an isolated subprocess."""
    code = """
import sys, types

# Inject fake orjson BEFORE importing json_fast
fake = types.ModuleType("orjson")
fake.loads = lambda data: {"mocked": True}
fake.dumps = lambda obj: b'{"mocked":true}'
sys.modules["orjson"] = fake

# Now import — it should pick up orjson
from servicenow_mcp.utils import json_fast

assert json_fast.BACKEND == "orjson", f"Expected orjson, got {json_fast.BACKEND}"
assert json_fast.loads("{}") == {"mocked": True}
assert json_fast.dumps({}) == '{"mocked":true}'
print("OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"orjson branch test failed: {result.stderr}"
    assert "OK" in result.stdout
