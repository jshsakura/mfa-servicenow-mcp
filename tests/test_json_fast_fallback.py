"""Tests for json_fast fallback (stdlib json) path.

The orjson branch is tested in test_json_fast.py via subprocess injection.
This file tests the stdlib fallback by importing json_fast in a subprocess
where orjson is blocked via builtins.__import__ override, forcing the ImportError path.
"""

import subprocess
import sys


def _block_orjson_code(test_body: str) -> str:
    prefix = """\
import sys, builtins

for key in list(sys.modules.keys()):
    if "orjson" in key or "json_fast" in key or "servicenow_mcp" in key:
        del sys.modules[key]

_real_import = builtins.__import__

def _blocking_import(name, *args, **kwargs):
    if name == "orjson":
        raise ImportError("orjson blocked for testing")
    return _real_import(name, *args, **kwargs)

builtins.__import__ = _blocking_import

from servicenow_mcp.utils import json_fast

assert json_fast.BACKEND == "json", f"Expected json, got {json_fast.BACKEND}"
"""
    return prefix + test_body + '\nprint("OK")\n'


def _run_subprocess(code: str):
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Failed: {result.stderr}"
    assert "OK" in result.stdout
    return result


def test_stdlib_fallback_loads():
    _run_subprocess(_block_orjson_code("""
data = json_fast.loads('{"hello": "world", "num": 42}')
assert data == {"hello": "world", "num": 42}
"""))


def test_stdlib_fallback_dumps_compact():
    _run_subprocess(_block_orjson_code("""
result = json_fast.dumps({"key": "value", "num": 42})
assert isinstance(result, str)
assert ": " not in result
assert ", " not in result
assert '"key":"value"' in result
"""))


def test_stdlib_fallback_dumps_non_ascii():
    _run_subprocess(_block_orjson_code(r"""
result = json_fast.dumps({"name": "\ud55c\uae00"})
assert "\ud55c\uae00" in result
"""))


def test_stdlib_fallback_loads_bytes():
    _run_subprocess(_block_orjson_code("""
data = json_fast.loads(b'{"bytes": true}')
assert data == {"bytes": True}
"""))


def test_stdlib_fallback_dumps_with_kwargs():
    _run_subprocess(_block_orjson_code("""
result = json_fast.dumps({"b": 2, "a": 1}, sort_keys=True)
assert result == '{"a":1,"b":2}'
"""))
