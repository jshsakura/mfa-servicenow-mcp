"""Tests for the local write journal (utils/write_journal + dispatch wiring).

Pinned invariants:
- Every CONFIRMED write appends one machine-readable JSONL line (host-split);
  reads never journal.
- Long string arguments are stored as sha256+length, never inline.
- Journaling is fire-and-forget: a broken journal dir can never fail a write.
"""

import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.utils import write_journal
from servicenow_mcp.utils.write_journal import _compact_value, record_write


def _read_lines(tmp_path):
    journal = tmp_path / "_write_journal"
    lines = []
    for f in sorted(journal.glob("*.jsonl")):
        lines.extend(json.loads(line) for line in f.read_text().splitlines() if line)
    return lines


class TestRecordWrite:
    def test_appends_host_split_jsonl(self, tmp_path):
        record_write(
            "https://dev.service-now.com",
            "admin",
            "manage_script_include",
            {"action": "update", "sys_id": "abc"},
            outcome="success",
            target_alias="dev",
        )
        record_write(
            "https://test.service-now.com",
            "admin",
            "update_remote_from_local",
            {"path": "/x"},
            outcome="rejected",
            error="CONFLICT",
        )
        journal = tmp_path / "_write_journal"
        assert (journal / "dev.service-now.com.jsonl").exists()
        assert (journal / "test.service-now.com.jsonl").exists()
        entries = _read_lines(tmp_path)
        assert {e["outcome"] for e in entries} == {"success", "rejected"}
        rejected = next(e for e in entries if e["outcome"] == "rejected")
        assert rejected["error"] == "CONFLICT"
        dev = next(e for e in entries if e["outcome"] == "success")
        assert dev["instance_alias"] == "dev"
        assert dev["user"] == "admin"
        assert dev["args"]["sys_id"] == "abc"

    def test_long_bodies_become_hashes(self, tmp_path):
        body = "var X = 1;\n" * 100
        record_write(
            "https://dev.service-now.com",
            "",
            "manage_portal_component",
            {"update_data": {"script": body}, "sys_id": "abc"},
            outcome="success",
        )
        entry = _read_lines(tmp_path)[0]
        stored = entry["args"]["update_data"]["script"]
        assert set(stored) == {"sha256", "length"}
        assert stored["length"] == len(body)

    def test_never_raises_on_broken_dir(self, tmp_path, monkeypatch):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("file blocks mkdir", encoding="utf-8")
        monkeypatch.setattr(write_journal, "_journal_dir", lambda: blocker / "journal")
        record_write("https://x.service-now.com", "", "t", {}, outcome="success")  # no raise

    def test_rotation_keeps_one_generation(self, tmp_path, monkeypatch):
        monkeypatch.setattr(write_journal, "_MAX_BYTES", 10)
        record_write("https://dev.service-now.com", "", "t1", {}, outcome="success")
        record_write("https://dev.service-now.com", "", "t2", {}, outcome="success")
        journal = tmp_path / "_write_journal"
        assert (journal / "dev.service-now.com.jsonl").exists()
        assert (journal / "dev.service-now.com.jsonl.1").exists()

    def test_compact_value_nested_and_capped_lists(self):
        out = _compact_value({"a": ["x" * 500] + list(range(30))})
        assert set(out["a"][0]) == {"sha256", "length"}
        assert len(out["a"]) == 20  # list capped


class TestDispatchWiring:
    """A confirmed write through the real dispatch must land in the journal."""

    def _server(self):
        from servicenow_mcp.server import ServiceNowMCP
        from servicenow_mcp.utils.config import ServerConfig

        prev = os.environ.get("MCP_TOOL_PACKAGE")
        os.environ["MCP_TOOL_PACKAGE"] = "full"
        try:
            return ServiceNowMCP(
                ServerConfig(
                    instance_url="https://test.service-now.com",
                    auth={"type": "basic", "basic": {"username": "admin", "password": "pw"}},
                )
            )
        finally:
            if prev is None:
                os.environ.pop("MCP_TOOL_PACKAGE", None)
            else:
                os.environ["MCP_TOOL_PACKAGE"] = prev

    @pytest.fixture
    def server(self):
        return self._server()

    def _swap_impl(self, server, name, impl):
        d = server.tool_definitions[name]
        server.tool_definitions[name] = (impl, d[1], d[2], d[3], d[4])

    @patch("servicenow_mcp.policies.run_post_confirm_guards", lambda *a, **k: None)
    @patch("servicenow_mcp.policies.run_write_guards", lambda *a, **k: None)
    def test_confirmed_write_is_journaled(self, server, tmp_path):
        self._swap_impl(
            server,
            "manage_user",
            lambda config, auth, params: {"success": True, "message": "ok"},
        )
        server.auth_manager = MagicMock()
        asyncio.run(
            server._call_tool_impl(
                "manage_user",
                {"action": "update", "user_id": "u1", "title": "Dev", "confirm": "approve"},
            )
        )
        entries = _read_lines(tmp_path)
        assert len(entries) == 1
        assert entries[0]["tool"] == "manage_user"
        assert entries[0]["outcome"] == "success"
        assert entries[0]["user"] == "admin"
        # The confirm token itself is stripped before journaling.
        assert "confirm" not in entries[0]["args"]

    def test_read_call_is_not_journaled(self, server, tmp_path):
        self._swap_impl(
            server, "manage_user", lambda config, auth, params: {"success": True, "users": []}
        )
        server.auth_manager = MagicMock()
        asyncio.run(server._call_tool_impl("manage_user", {"action": "list"}))
        assert _read_lines(tmp_path) == []
