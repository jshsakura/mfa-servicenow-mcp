"""Orchestrator-level resume tests for download_app_sources.

The point of resume is: a call that dies partway (the 120s client timeout)
must, on re-invocation, skip the stages already finished AND still produce a
complete result — nothing downloaded twice, nothing missed.
"""

from unittest.mock import patch

import pytest

from servicenow_mcp.tools import source_resume as sr
from servicenow_mcp.tools.source_tools import DownloadAppSourcesParams, download_app_sources


@pytest.fixture
def config():
    cfg = type("Cfg", (), {})()
    cfg.instance_url = "https://dev.example.com"
    return cfg


@pytest.fixture
def auth():
    return object()


def _empty_group_result(source_types):
    return {
        "type_results": {t: {"count": 0} for t in source_types},
        "manifest_entries": [],
        "warnings": [],
        "total_files": 0,
        "deletion_candidates": {},
    }


def _params(tmp_path, **over):
    base = dict(
        scope="x_app",
        include_widget_sources=False,
        include_schema=False,
        auto_resolve_deps=False,
        output_dir=str(tmp_path),
    )
    base.update(over)
    return DownloadAppSourcesParams(**base)


def test_timeout_then_resume_skips_finished_groups_and_completes(config, auth, tmp_path):
    calls_run1 = []
    calls_run2 = []

    # Run 1: blow up on the 3rd source-group call to simulate the client timeout.
    def fake_run1(*args, **kwargs):
        st = kwargs["source_types"]
        calls_run1.append(tuple(st))
        if len(calls_run1) == 3:
            raise TimeoutError("simulated 120s client timeout mid-download")
        return _empty_group_result(st)

    with patch("servicenow_mcp.tools.source_tools._download_source_types", side_effect=fake_run1):
        with pytest.raises(TimeoutError):
            download_app_sources(config, auth, _params(tmp_path))

    # Progress persisted exactly the two groups that finished before the crash.
    progress = sr.load_progress(tmp_path, sr.params_fingerprint(_params(tmp_path)))
    assert progress is not None
    assert set(progress) == {"group:0", "group:1"}

    # Run 2: nothing raises. Finished groups must NOT be re-downloaded.
    def fake_run2(*args, **kwargs):
        st = kwargs["source_types"]
        calls_run2.append(tuple(st))
        return _empty_group_result(st)

    with patch("servicenow_mcp.tools.source_tools._download_source_types", side_effect=fake_run2):
        result = download_app_sources(config, auth, _params(tmp_path))

    assert result["success"] is True
    # group:0 and group:1 were replayed from disk → not re-fetched.
    assert result["resumed_stages"] == ["group:0", "group:1"]
    # The first two groups from run 1 are exactly the ones skipped in run 2.
    assert calls_run1[0] not in calls_run2
    assert calls_run1[1] not in calls_run2
    # The group that crashed (run1 call #3) IS re-fetched in run 2.
    assert calls_run1[2] in calls_run2
    # Manifest written and progress cleared on full completion.
    assert (tmp_path / "_manifest.json").exists()
    assert not sr.progress_path(tmp_path).exists()


def test_completed_run_leaves_no_progress_file(config, auth, tmp_path):
    with patch(
        "servicenow_mcp.tools.source_tools._download_source_types",
        side_effect=lambda *a, **k: _empty_group_result(k["source_types"]),
    ):
        result = download_app_sources(config, auth, _params(tmp_path))

    assert result["success"] is True
    assert "resumed_stages" not in result
    assert not sr.progress_path(tmp_path).exists()


def test_changed_params_ignore_stale_progress(config, auth, tmp_path):
    # Seed a stale progress file under a different fingerprint.
    sr.save_stage(
        tmp_path,
        sr.params_fingerprint(_params(tmp_path, only_active=False)),
        "group:0",
        {"type_results": {}, "files": 0},
    )

    calls = []

    def fake(*args, **kwargs):
        calls.append(tuple(kwargs["source_types"]))
        return _empty_group_result(kwargs["source_types"])

    with patch("servicenow_mcp.tools.source_tools._download_source_types", side_effect=fake):
        # Different params → fingerprint mismatch → full run, nothing skipped.
        result = download_app_sources(config, auth, _params(tmp_path, only_active=True))

    assert result["success"] is True
    assert "resumed_stages" not in result
    # All 8 source groups + global were actually fetched (none skipped).
    assert len(calls) >= 9
