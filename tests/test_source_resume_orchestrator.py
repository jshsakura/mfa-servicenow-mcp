"""Orchestrator-level resume tests for download_app_sources.

The point of resume is: a call that dies partway (the 120s client timeout)
must, on re-invocation, skip the stages already finished AND still produce a
complete result — nothing downloaded twice, nothing missed.
"""

import threading
import time
from unittest.mock import patch

import pytest

from servicenow_mcp.tools import source_resume as sr
from servicenow_mcp.tools import source_tools
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


def test_background_start_poll_result(config, auth, tmp_path, monkeypatch):
    """background=true: first call starts a thread and returns immediately;
    polling (same args) reports running, then returns the final result. Same
    tool, no second tool, no client-side timeout."""
    source_tools._BG_JOBS.clear()
    # Keep the server-side long-poll tiny so the test stays fast.
    monkeypatch.setattr(source_tools, "_BG_POLL_MAX_BLOCK_SECONDS", 0.05)
    monkeypatch.setattr(source_tools, "_BG_POLL_TICK_SECONDS", 0.02)
    release = threading.Event()

    def slow_group(*args, **kwargs):
        # Block so the test can observe the "running" state deterministically.
        release.wait(timeout=5)
        return _empty_group_result(kwargs["source_types"])

    with patch("servicenow_mcp.tools.source_tools._download_source_types", side_effect=slow_group):
        started = download_app_sources(config, auth, _params(tmp_path, background=True))
        assert started["background"] is True
        assert started["status"] == "started"

        # Worker is blocked → a poll must report running, NOT start a 2nd job.
        polled = download_app_sources(config, auth, _params(tmp_path, background=True))
        assert polled["status"] == "running"
        assert len(source_tools._BG_JOBS) == 1

        # Let the worker finish, then poll for the final result.
        release.set()
        result = None
        for _ in range(100):
            r = download_app_sources(config, auth, _params(tmp_path, background=True))
            if r.get("status") == "running":
                time.sleep(0.02)
                continue
            result = r
            break

    assert result is not None
    assert result["success"] is True


def test_background_poll_blocks_until_cap_then_reports_running(config, auth, tmp_path, monkeypatch):
    """A poll on a still-running job blocks server-side up to the cap (not a
    busy 1s spin), then returns running with a no-sleep-needed hint."""
    source_tools._BG_JOBS.clear()
    monkeypatch.setattr(source_tools, "_BG_POLL_MAX_BLOCK_SECONDS", 0.2)
    monkeypatch.setattr(source_tools, "_BG_POLL_TICK_SECONDS", 0.04)
    release = threading.Event()

    def slow_group(*args, **kwargs):
        release.wait(timeout=5)
        return _empty_group_result(kwargs["source_types"])

    with patch("servicenow_mcp.tools.source_tools._download_source_types", side_effect=slow_group):
        download_app_sources(config, auth, _params(tmp_path, background=True))

        start = time.perf_counter()
        polled = download_app_sources(config, auth, _params(tmp_path, background=True))
        elapsed = time.perf_counter() - start

        # Blocked roughly the cap rather than returning instantly.
        assert polled["status"] == "running"
        assert elapsed >= 0.18
        assert polled["next_poll_after_seconds"] == 0
        assert "server-side" in polled["message"]

        release.set()


def test_background_poll_returns_early_when_job_finishes_midwait(
    config, auth, tmp_path, monkeypatch
):
    """The long-poll must not wait the full cap once the worker finishes — it
    returns the final result as soon as the job flips to done."""
    source_tools._BG_JOBS.clear()
    # Large cap so a full-cap wait would be obvious; the poll must beat it.
    monkeypatch.setattr(source_tools, "_BG_POLL_MAX_BLOCK_SECONDS", 5.0)
    monkeypatch.setattr(source_tools, "_BG_POLL_TICK_SECONDS", 0.02)
    release = threading.Event()

    def slow_group(*args, **kwargs):
        release.wait(timeout=5)
        return _empty_group_result(kwargs["source_types"])

    with patch("servicenow_mcp.tools.source_tools._download_source_types", side_effect=slow_group):
        download_app_sources(config, auth, _params(tmp_path, background=True))

        # Release shortly after the poll starts blocking; it should return well
        # before the 5s cap.
        timer = threading.Timer(0.1, release.set)
        timer.start()
        start = time.perf_counter()
        result = download_app_sources(config, auth, _params(tmp_path, background=True))
        elapsed = time.perf_counter() - start
        timer.cancel()

    assert elapsed < 2.0
    assert result["success"] is True


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


# ---------------------------------------------------------------------------
# A finished background job is an answer to ONE ask, not a standing reply
# ---------------------------------------------------------------------------
#
# Found in production, on a server that had been up three days: a morning's
# re-download of a scope came back in 3ms with success=true, a duration_ms of
# ~118s nobody had spent, and counts from the previous week's run. No argument
# the caller could pass escaped it — including resume=false, which is the one
# knob that means "download it again" and which was not part of the job key.


def _run_bg(config, auth, tmp_path, **over):
    return download_app_sources(config, auth, _params(tmp_path, background=True, **over))


def _finish_one_job(config, auth, tmp_path, **over):
    """Start and drain a background job so its result is stored."""
    with patch(
        "servicenow_mcp.tools.source_tools._download_source_types",
        side_effect=lambda *a, **k: _empty_group_result(k["source_types"]),
    ):
        _run_bg(config, auth, tmp_path, **over)
        for _ in range(200):
            r = _run_bg(config, auth, tmp_path, **over)
            if r.get("status") != "running":
                return r
            time.sleep(0.01)
    raise AssertionError("background job never finished")


def test_finished_job_expires_and_the_next_call_downloads_again(
    config, auth, tmp_path, monkeypatch
):
    source_tools._BG_JOBS.clear()
    monkeypatch.setattr(source_tools, "_BG_POLL_MAX_BLOCK_SECONDS", 0.05)
    monkeypatch.setattr(source_tools, "_BG_POLL_TICK_SECONDS", 0.02)
    monkeypatch.setattr(source_tools, "_BG_JOB_RESULT_TTL_SECONDS", 0.0)

    first = _finish_one_job(config, auth, tmp_path)
    assert first["success"] is True

    # TTL elapsed: the stored answer is gone, so an identical call must do work
    # rather than hand back the old dict.
    calls = []

    def _count(*a, **k):
        calls.append(tuple(k["source_types"]))
        return _empty_group_result(k["source_types"])

    with patch("servicenow_mcp.tools.source_tools._download_source_types", side_effect=_count):
        again = _run_bg(config, auth, tmp_path)
        assert again["status"] == "started"
        for _ in range(200):
            r = _run_bg(config, auth, tmp_path)
            if r.get("status") != "running":
                break
            time.sleep(0.01)

    assert calls, "an expired job replayed instead of downloading"


def test_a_re_delivered_result_says_it_is_a_replay(config, auth, tmp_path, monkeypatch):
    """Within the window the stored result is still worth handing back — but a
    fast success=true is indistinguishable from a fresh run unless it says so."""
    source_tools._BG_JOBS.clear()
    monkeypatch.setattr(source_tools, "_BG_POLL_MAX_BLOCK_SECONDS", 0.05)
    monkeypatch.setattr(source_tools, "_BG_POLL_TICK_SECONDS", 0.02)
    monkeypatch.setattr(source_tools, "_BG_JOB_RESULT_TTL_SECONDS", 60.0)

    first = _finish_one_job(config, auth, tmp_path)
    assert "replayed" not in first

    second = _run_bg(config, auth, tmp_path)
    assert second["replayed"] is True
    assert "REPLAY" in second["message"]
    assert "downloaded nothing" in second["message"]


def test_resume_false_is_a_different_job_than_resume_true(config, auth, tmp_path, monkeypatch):
    """resume=false must not be answered by the run it was trying to replace."""
    source_tools._BG_JOBS.clear()
    monkeypatch.setattr(source_tools, "_BG_POLL_MAX_BLOCK_SECONDS", 0.05)
    monkeypatch.setattr(source_tools, "_BG_POLL_TICK_SECONDS", 0.02)
    monkeypatch.setattr(source_tools, "_BG_JOB_RESULT_TTL_SECONDS", 60.0)

    _finish_one_job(config, auth, tmp_path, resume=True)

    with patch(
        "servicenow_mcp.tools.source_tools._download_source_types",
        side_effect=lambda *a, **k: _empty_group_result(k["source_types"]),
    ):
        forced = _run_bg(config, auth, tmp_path, resume=False)

    # A new job, not the stored result of the resume=true run.
    assert forced["status"] == "started"
    assert len(source_tools._BG_JOBS) == 2


def test_a_failed_job_does_not_answer_the_retry(config, auth, tmp_path, monkeypatch):
    """A sticky failure is the same defect pointing the other way: 'try again'
    could never try anything."""
    source_tools._BG_JOBS.clear()
    monkeypatch.setattr(source_tools, "_BG_POLL_MAX_BLOCK_SECONDS", 0.05)
    monkeypatch.setattr(source_tools, "_BG_POLL_TICK_SECONDS", 0.02)

    with patch(
        "servicenow_mcp.tools.source_tools._download_source_types",
        side_effect=RuntimeError("boom"),
    ):
        _run_bg(config, auth, tmp_path)
        failed = None
        for _ in range(200):
            r = _run_bg(config, auth, tmp_path)
            if r.get("status") not in ("running", "started"):
                failed = r
                break
            time.sleep(0.01)

    assert failed is not None and failed["status"] == "failed"
    assert "NOT kept" in failed["message"]
    assert source_tools._BG_JOBS == {}, "the failure was kept and would answer the retry"
