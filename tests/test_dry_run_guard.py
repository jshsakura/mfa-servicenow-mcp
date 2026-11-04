"""dry_run=true writes nothing — on every tool, enforced once in the server.

A sweep found 33 write actions that accepted ``dry_run`` and sent the real
request anyway. These tests pin the server-side guard and sweep every
registered tool, so a tool added later cannot reintroduce it.
"""

from __future__ import annotations

import asyncio
import typing
from typing import Any, Dict, List, Tuple, get_args, get_origin
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig
from servicenow_mcp.utils.dry_run_guard import (
    WRITE_METHODS,
    DryRunAuthManager,
    run_with_dry_run_guard,
)
from servicenow_mcp.utils.registry import discover_tools

SID = "aaaa1111bbbb2222cccc3333dddd4444"

CONFIG = ServerConfig(
    instance_url="https://test.service-now.com",
    auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
)


class _Resp:
    """A Table API answer shaped enough for any tool to reach its write."""

    def __init__(self, url: str) -> None:
        tail = url.split("?")[0].rstrip("/").split("/")[-1]
        self._single = tail == SID
        self.status_code = 200
        self.ok = True
        self.headers = {"X-Total-Count": "1", "Content-Type": "application/json"}
        self.text = "{}"
        self.content = b"{}"

    @staticmethod
    def _row() -> Dict[str, Any]:
        keys = (
            "sys_id name title label table collection application sys_scope cat_item "
            "category script sys_updated_on sys_created_by sys_updated_by update_set "
            "target_name type action payload"
        ).split()
        row: Dict[str, Any] = {k: SID for k in keys}
        row.update({"sys_mod_count": "1", "state": "in progress", "active": "true"})
        return row

    def json(self) -> Dict[str, Any]:
        return {"result": self._row() if self._single else [self._row()]}

    def raise_for_status(self) -> None:
        return None


def _recording_auth() -> Tuple[MagicMock, List[Tuple[str, str]]]:
    calls: List[Tuple[str, str]] = []
    auth = MagicMock()
    auth.get_headers.return_value = {}

    def make_request(method, url, *a, **k):
        calls.append((str(method).upper(), url))
        return _Resp(url)

    auth.make_request.side_effect = make_request
    return auth, calls


def _fill(ann: Any) -> Any:
    origin, args = get_origin(ann), get_args(ann)
    if origin is typing.Union:
        non_null = [a for a in args if a is not type(None)]
        return _fill(non_null[0]) if non_null else None
    if origin is typing.Literal:
        return args[0]
    if origin is list:
        return [_fill(args[0]) if args else SID]
    if origin is dict:
        return {"name": SID}
    return {str: SID, int: 1, float: 1.0}.get(ann)


def _dry_run_cases() -> List[Tuple[str, Any]]:
    cases = []
    for name, (_func, model, *_rest) in sorted(discover_tools().items()):
        fields = getattr(model, "model_fields", {})
        if "dry_run" not in fields:
            continue
        actions = list(get_args(fields["action"].annotation)) if "action" in fields else [None]
        for action in actions or [None]:
            cases.append((name, action))
    return cases


def _build_params(model: Any, action: Any) -> Any:
    kwargs: Dict[str, Any] = {}
    for fname, field in model.model_fields.items():
        if fname in ("action", "dry_run") or fname.startswith("confirm"):
            continue
        value = _fill(field.annotation)
        if value is not None:
            kwargs[fname] = value
    if action is not None:
        kwargs["action"] = action
    kwargs["dry_run"] = True
    return model(**kwargs)


_CASES = _dry_run_cases()


def test_the_sweep_covers_the_tools_that_leaked():
    names = {n for n, _ in _CASES}
    assert {"manage_catalog", "manage_incident", "manage_portal_layout", "manage_user"} <= names
    assert len(_CASES) > 60


@pytest.mark.parametrize("tool,action", _CASES, ids=[f"{n}:{a}" for n, a in _CASES])
def test_no_write_leaves_under_dry_run(tool, action):
    func, model, *_ = discover_tools()[tool]
    try:
        params = _build_params(model, action)
    except Exception:
        pytest.skip("generic params do not satisfy this action's validator")
    auth, calls = _recording_auth()
    try:
        run_with_dry_run_guard(func, CONFIG, auth, params)
    except Exception:
        pass  # a refusal is fine; a sent write is not
    writes = [c for c in calls if c[0] in WRITE_METHODS]
    assert writes == [], f"{tool}:{action} sent {writes} under dry_run=true"


class TestGuard:
    @staticmethod
    def _params(dry_run):
        p = MagicMock()
        p.dry_run = dry_run
        return p

    def test_first_write_is_captured_not_sent(self):
        auth, calls = _recording_auth()

        def impl(config, am, params):
            am.make_request("GET", f"{config.instance_url}/api/now/table/incident")
            am.make_request(
                "POST",
                f"{config.instance_url}/api/now/table/incident",
                json={"short_description": "x", "script": "y" * 1000},
            )
            return {"success": True, "message": "created"}

        result = run_with_dry_run_guard(impl, CONFIG, auth, self._params(True))
        assert calls == [("GET", "https://test.service-now.com/api/now/table/incident")]
        assert result["dry_run"] is True
        assert result["would_send"]["method"] == "POST"
        assert result["would_send"]["table"] == "incident"
        assert result["would_send"]["body"]["short_description"] == "x"
        assert result["would_send"]["body"]["script"] == "<1,000 characters, as sent>"
        assert "created" not in result["message"]

    def test_target_sys_id_is_named(self):
        auth, _ = _recording_auth()

        def impl(config, am, params):
            am.make_request("DELETE", f"{config.instance_url}/api/now/table/sp_row/{SID}")

        result = run_with_dry_run_guard(impl, CONFIG, auth, self._params(True))
        assert result["would_send"] == {
            "method": "DELETE",
            "path": f"/api/now/table/sp_row/{SID}",
            "table": "sp_row",
            "sys_id": SID,
        }

    def test_a_tool_catching_exception_cannot_swallow_the_stop(self):
        auth, calls = _recording_auth()

        def impl(config, am, params):
            try:
                am.make_request("PATCH", f"{config.instance_url}/api/now/table/x/{SID}", json={})
            except Exception:
                return {"success": False, "message": "failed"}
            am.make_request("POST", f"{config.instance_url}/api/now/table/y", json={})

        result = run_with_dry_run_guard(impl, CONFIG, auth, self._params(True))
        assert result["dry_run"] is True and result["would_send"]["method"] == "PATCH"
        assert calls == []

    def test_a_native_preview_is_returned_unchanged(self):
        auth, _ = _recording_auth()
        native = {"success": True, "dry_run": True, "diff": "..."}
        result = run_with_dry_run_guard(lambda c, a, p: native, CONFIG, auth, self._params(True))
        assert result is native

    def test_without_dry_run_the_real_manager_is_used(self):
        auth, calls = _recording_auth()

        def impl(config, am, params):
            assert am is auth
            am.make_request("POST", f"{config.instance_url}/api/now/table/x", json={})
            return "sent"

        assert run_with_dry_run_guard(impl, CONFIG, auth, self._params(False)) == "sent"
        assert calls == [("POST", "https://test.service-now.com/api/now/table/x")]

    def test_params_without_dry_run_pass_through(self):
        auth, _ = _recording_auth()
        sentinel = object()
        assert run_with_dry_run_guard(lambda c, a, p: sentinel, CONFIG, auth, object()) is sentinel

    def test_proxy_forwards_other_attributes(self):
        auth, _ = _recording_auth()
        assert DryRunAuthManager(auth).get_headers() == {}


class TestServerWiring:
    def test_invoke_impl_applies_the_guard(self):
        from servicenow_mcp.server import ServiceNowMCP

        auth, calls = _recording_auth()

        def impl(config, am, params):
            am.make_request("POST", f"{config.instance_url}/api/now/table/x", json={"a": 1})
            return {"success": True}

        params = MagicMock()
        params.dry_run = True
        server = MagicMock()
        server._progress_channel.return_value = (None, None)
        result = asyncio.run(
            ServiceNowMCP._invoke_impl(server, "manage_x", impl, CONFIG, auth, params)
        )
        assert calls == []
        assert result["would_send"]["body"] == {"a": 1}

    def test_journal_records_a_preview_as_dry_run_not_success(self):
        from servicenow_mcp.server import ServiceNowMCP

        assert ServiceNowMCP._result_outcome({"success": True, "dry_run": True}) == "dry_run"
        assert ServiceNowMCP._result_outcome({"success": False, "dry_run": True}) == "rejected"
        assert ServiceNowMCP._result_outcome({"success": True}) == "success"
