"""Tests for utils.download_map.merge_map_file."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from servicenow_mcp.utils.download_map import merge_map_file


def _writer_compact(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def _writer_indented(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class TestMergeMapFile:
    def test_creates_file_when_absent(self, tmp_path):
        path = tmp_path / "_map.json"

        result = merge_map_file(
            path,
            {"alpha": "id-A"},
            writer=_writer_compact,
            label="widget",
        )

        assert result == {"alpha": "id-A"}
        assert json.loads(path.read_text()) == {"alpha": "id-A"}

    def test_merges_with_existing_preserves_unrelated_keys(self, tmp_path):
        path = tmp_path / "_map.json"
        path.write_text(
            json.dumps({"alpha": "id-A", "beta": "id-B", "gamma": "id-G"}),
            encoding="utf-8",
        )

        result = merge_map_file(
            path,
            {"alpha": "id-A2", "delta": "id-D"},
            writer=_writer_compact,
            label="widget",
        )

        assert result == {
            "alpha": "id-A2",
            "beta": "id-B",
            "gamma": "id-G",
            "delta": "id-D",
        }
        assert json.loads(path.read_text()) == result

    def test_logs_summary_counts(self, tmp_path, caplog):
        path = tmp_path / "_map.json"
        path.write_text(
            json.dumps({"alpha": "id-A", "beta": "id-B", "gamma": "id-G"}),
            encoding="utf-8",
        )

        with caplog.at_level(logging.INFO, logger="servicenow_mcp.utils.download_map"):
            merge_map_file(
                path,
                {"alpha": "id-A2", "delta": "id-D"},
                writer=_writer_compact,
                label="widget",
            )

        record = next(r for r in caplog.records if "Merged widget map" in r.message)
        msg = record.getMessage()
        assert "existing=3" in msg
        assert "new=2" in msg
        assert "added=1" in msg  # delta
        assert "updated=1" in msg  # alpha changed
        assert "preserved=2" in msg  # beta, gamma
        assert "total=4" in msg

    def test_targeted_download_does_not_lose_prior_widgets(self, tmp_path):
        """Reproduces the v1.11.42 bug fix scenario.

        Full scope download writes 100 widgets. Targeted download with one
        widget_id should not blank the other 99.
        """
        path = tmp_path / "_map.json"
        full_map = {f"widget_{i}": f"sys_{i}" for i in range(100)}
        path.write_text(json.dumps(full_map), encoding="utf-8")

        merge_map_file(
            path,
            {"widget_5": "sys_5_updated"},
            writer=_writer_compact,
            label="widget",
        )

        merged = json.loads(path.read_text())
        assert len(merged) == 100
        assert merged["widget_5"] == "sys_5_updated"
        assert merged["widget_0"] == "sys_0"
        assert merged["widget_99"] == "sys_99"

    def test_recovers_from_corrupt_json(self, tmp_path, caplog):
        path = tmp_path / "_map.json"
        path.write_text("{ this is not valid json", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="servicenow_mcp.utils.download_map"):
            result = merge_map_file(
                path,
                {"alpha": "id-A"},
                writer=_writer_compact,
                label="widget",
            )

        assert result == {"alpha": "id-A"}
        assert any("not valid JSON" in r.getMessage() for r in caplog.records)

    def test_recovers_when_top_level_is_array(self, tmp_path, caplog):
        path = tmp_path / "_map.json"
        path.write_text(json.dumps(["unexpected", "list"]), encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="servicenow_mcp.utils.download_map"):
            result = merge_map_file(
                path,
                {"alpha": "id-A"},
                writer=_writer_compact,
                label="widget",
            )

        assert result == {"alpha": "id-A"}
        assert any("top-level" in r.getMessage() for r in caplog.records)

    def test_uses_caller_writer_format(self, tmp_path):
        """Indented writer should produce indented output even after merge."""
        path = tmp_path / "_map.json"

        merge_map_file(
            path,
            {"alpha": "id-A", "beta": "id-B"},
            writer=_writer_indented,
            label="src",
        )

        text = path.read_text()
        # indented writer adds newlines
        assert "\n" in text
        assert json.loads(text) == {"alpha": "id-A", "beta": "id-B"}

    def test_empty_existing_file_treated_as_empty(self, tmp_path):
        path = tmp_path / "_map.json"
        path.write_text("", encoding="utf-8")

        result = merge_map_file(
            path,
            {"alpha": "id-A"},
            writer=_writer_compact,
            label="widget",
        )

        assert result == {"alpha": "id-A"}

    def test_no_op_when_new_entries_match_existing(self, tmp_path, caplog):
        path = tmp_path / "_map.json"
        path.write_text(json.dumps({"alpha": "id-A"}), encoding="utf-8")

        with caplog.at_level(logging.INFO, logger="servicenow_mcp.utils.download_map"):
            merge_map_file(
                path,
                {"alpha": "id-A"},
                writer=_writer_compact,
                label="widget",
            )

        msg = next(r.getMessage() for r in caplog.records if "Merged" in r.message)
        assert "added=0" in msg
        assert "updated=0" in msg
        assert "preserved=0" in msg
