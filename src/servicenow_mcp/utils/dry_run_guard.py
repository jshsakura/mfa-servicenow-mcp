"""Make ``dry_run=true`` mean "nothing is written" on every tool, not only on the
ones that remembered to read it.

A sweep that called every write action with ``dry_run=true`` against a recording
fake found 33 of them sending the real POST/PATCH/PUT/DELETE: the field was in
the schema, the model accepted it, and the code path never looked at it. A
caller who asked for a preview before approving got the write instead.

So the server enforces it once, here, rather than trusting each tool:

* reads still go to the live instance, so every lookup and refusal a tool makes
  before writing runs for real;
* the FIRST write request is not sent; it is captured and returned as the
  preview — the method, the target and the exact body the tool built.

A tool with its own preview never reaches a write under ``dry_run`` and is
returned unchanged. A tool whose later steps depend on the first write's
response (create, then link the created record) can only be shown that first
request; the preview says so rather than inventing a sys_id to carry on with.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Long string values (a script body, an HTML template) are the caller's own input;
# echoing them back is context spent on nothing. Size is reported instead.
_MAX_ECHO_CHARS = 400


class _WriteIntercepted(BaseException):
    """Raised at the first write under dry_run.

    BaseException, not Exception: tools wrap their network calls in
    ``except Exception`` and turn failures into ``success: False``. This must
    pass through those handlers, or the tool would report its own refusal.
    """


class DryRunAuthManager:
    """Proxy that forwards reads and captures — never sends — the first write."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.planned: Optional[Dict[str, Any]] = None

    def make_request(self, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
        if str(method).upper() in WRITE_METHODS:
            self.planned = _describe_request(str(method).upper(), url, kwargs)
            raise _WriteIntercepted()
        return self._inner.make_request(method, url, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _echo(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_ECHO_CHARS:
        return f"<{len(value):,} characters, as sent>"
    if isinstance(value, dict):
        return {k: _echo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_echo(v) for v in value]
    return value


def _describe_request(method: str, url: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    path = urlparse(url).path
    planned: Dict[str, Any] = {"method": method, "path": path}
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 4 and parts[:3] == ["api", "now", "table"]:
        planned["table"] = parts[3]
        if len(parts) >= 5:
            planned["sys_id"] = parts[4]
    body = kwargs.get("json")
    if body is None:
        body = kwargs.get("data")
    if body is not None:
        planned["body"] = _echo(body)
    return planned


def run_with_dry_run_guard(
    impl_func: Callable[..., Any], config: Any, auth_manager: Any, params: Any
) -> Any:
    """Run ``impl_func``; under ``dry_run=true`` no write request leaves the process."""
    if getattr(params, "dry_run", False) is not True:
        return impl_func(config, auth_manager, params)
    proxy = DryRunAuthManager(auth_manager)
    try:
        result = impl_func(config, proxy, params)
    except _WriteIntercepted:
        result = None
    if proxy.planned is None:
        # No write was attempted: the tool's own preview (or a read) stands.
        return result
    return {
        "success": True,
        "dry_run": True,
        "message": (
            "dry_run: nothing was written. This is the request the call would "
            "send; the checks before it ran against the live instance."
        ),
        "would_send": proxy.planned,
        "note": (
            "Only the first write is shown. Steps after it depend on its "
            "response and were not run."
        ),
    }
