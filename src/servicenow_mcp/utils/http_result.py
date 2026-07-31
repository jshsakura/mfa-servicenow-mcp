"""Parse a ServiceNow HTTP body without assuming it is a JSON object.

``response.json().get("result")`` is written ~25 times across this codebase, and
every one of them assumes the body decodes to a dict. A dead or redirected
session does not return a dict — it returns an HTML login page, a bare string, or
a list — and the caller dies with ``'str' object has no attribute 'get'``.

That traceback tells the operator nothing. It is not even wrong in an informative
way: it names a Python type, not the thing that actually happened, which is that
the session stopped being usable mid-run. Observed live: two consecutive pushes
failed with it, the record was verified untouched by its sys_mod_count, and the
same push succeeded after reconnecting.

So the body is checked and the failure is named.
"""

from __future__ import annotations

from typing import Any, Dict


def json_object(response: Any, what: str = "response") -> Dict[str, Any]:
    """The body as a dict, or ValueError explaining what came back instead.

    ``what`` names the call site in the message ("fetch sp_widget/abc123"), so the
    error says which request went wrong rather than only that one did.
    """
    try:
        body = response.json()
    except Exception as exc:  # json module raises several unrelated types
        text = (getattr(response, "text", "") or "")[:200]
        raise ValueError(
            f"{what}: the instance did not return JSON ({exc}). This is what an expired "
            f"or redirected session looks like — the reply is usually a login page. "
            f"Re-authenticate and retry. First bytes: {text!r}"
        ) from exc
    if isinstance(body, dict):
        return body
    raise ValueError(
        f"{what}: expected a JSON object, got {type(body).__name__}. A session that has "
        f"stopped being usable returns this shape; re-authenticate and retry. "
        f"Body starts: {str(body)[:200]!r}"
    )


def json_result(response: Any, what: str = "response", default: Any = None) -> Any:
    """``body["result"]`` with the same guard. ``default`` when absent."""
    return json_object(response, what).get("result", default)
