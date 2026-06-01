"""Tests for resumable download progress (source_resume).

Guards the "nothing gets missed" invariants:
- a finished stage is skipped on resume,
- a params change invalidates stale progress (full re-run),
- a completed run clears its progress file,
- corrupt/missing progress degrades to a fresh start.
"""

from servicenow_mcp.tools import source_resume as sr
from servicenow_mcp.tools.source_tools import DownloadAppSourcesParams


def _params(**over):
    base = dict(scope="x_app")
    base.update(over)
    return DownloadAppSourcesParams(**base)


def test_save_then_load_roundtrips_finished_stage(tmp_path):
    fp = sr.params_fingerprint(_params())
    sr.save_stage(tmp_path, fp, "group:0", {"type_results": {"script_include": {"count": 3}}})

    stages = sr.load_progress(tmp_path, fp)

    assert stages is not None
    assert stages["group:0"]["type_results"]["script_include"]["count"] == 3


def test_load_returns_none_when_no_progress(tmp_path):
    assert sr.load_progress(tmp_path, "deadbeef") is None


def test_fingerprint_mismatch_starts_fresh(tmp_path):
    fp_a = sr.params_fingerprint(_params(only_active=False))
    sr.save_stage(tmp_path, fp_a, "group:0", {"type_results": {}})

    fp_b = sr.params_fingerprint(_params(only_active=True))

    assert fp_a != fp_b
    assert sr.load_progress(tmp_path, fp_b) is None


def test_save_stage_accumulates_multiple_stages(tmp_path):
    fp = sr.params_fingerprint(_params())
    sr.save_stage(tmp_path, fp, "portal", {"files": 1})
    sr.save_stage(tmp_path, fp, "group:0", {"files": 2})

    stages = sr.load_progress(tmp_path, fp)

    assert set(stages) == {"portal", "group:0"}


def test_clear_progress_removes_file(tmp_path):
    fp = sr.params_fingerprint(_params())
    sr.save_stage(tmp_path, fp, "portal", {})
    assert sr.progress_path(tmp_path).exists()

    sr.clear_progress(tmp_path)

    assert not sr.progress_path(tmp_path).exists()


def test_corrupt_progress_file_starts_fresh(tmp_path):
    sr.progress_path(tmp_path).write_text("{not json", encoding="utf-8")

    assert sr.load_progress(tmp_path, "any") is None


def test_clear_progress_is_idempotent(tmp_path):
    sr.clear_progress(tmp_path)  # no file yet — must not raise
    assert not sr.progress_path(tmp_path).exists()
