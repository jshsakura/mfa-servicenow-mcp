"""Atomicity invariants for the cross-process login lock and session cache.

Both defects fixed in v1.19.11 are races that the old code lost:

* `_acquire_login_lock` checked `os.path.exists()` and then wrote the file.
  Two MCP hosts starting together both saw "no lock", both wrote it, both
  believed they held it, and both opened a browser window (issue #30). The
  claim is now an O_CREAT|O_EXCL create — the kernel picks exactly one winner.

* `_save_session_to_disk` truncated the live file in place. Siblings poll that
  file by mtime, so they could stat the bumped mtime and read a half-written
  credential blob. The write now lands via a private temp file + os.replace.

The concurrency tests below run REAL threads against a REAL filesystem — no
mock decides the winner. Reverting either fix makes them fail.
"""

import json
import os
import stat
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import AuthType

RACERS = 8


def _lock_manager(tmp_path):
    manager = AuthManager.__new__(AuthManager)
    manager._login_lock_path = str(tmp_path / "session_host_user.lock")
    return manager


def _race_for_lock(tmp_path, racers=RACERS):
    """Fire `racers` threads at the same lock path; return their verdicts."""
    barrier = threading.Barrier(racers)
    verdicts = []
    guard = threading.Lock()

    def _claim():
        manager = _lock_manager(tmp_path)
        barrier.wait()  # maximize the overlap
        got = manager._acquire_login_lock()
        with guard:
            verdicts.append(got)

    # The O_EXCL winner leaves a 0-byte lock for the microseconds between the
    # create and the payload write. `_collect_lock_with_no_timestamp` collects an
    # empty lock older than LOGIN_LOCK_CLAIM_GRACE_SECONDS as "abandoned mid-claim"
    # — correct in production (a multi-second gap on a one-syscall write means a
    # dead claimant). But under coverage's sys.settrace + N GIL-bound threads on a
    # slow CI runner, a LIVE winner can be descheduled past the 5 s grace, and a
    # collector then reaps its lock and wins too — two winners, a flaky failure of
    # the very invariant this asserts (proven: GRACE=5 collects a 6 s-old empty
    # lock; GRACE huge backs off). Widen the grace so the harness's own starvation
    # can't be misread as death; O_EXCL exclusivity and the single-winner check are
    # unchanged. The empty-vs-aged boundary itself is pinned deterministically by
    # test_a_lock_claimed_moments_ago_is_not_collected_as_corrupt.
    threads = [threading.Thread(target=_claim) for _ in range(racers)]
    with patch.object(AuthManager, "LOGIN_LOCK_CLAIM_GRACE_SECONDS", 3600.0):
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
    return verdicts


class TestLoginLockIsExclusive:
    def test_exactly_one_racer_wins_a_free_lock(self, tmp_path):
        """The bug: both hosts win, both open a browser window."""
        verdicts = _race_for_lock(tmp_path)

        assert len(verdicts) == RACERS
        assert sum(verdicts) == 1, (
            f"{sum(verdicts)} of {RACERS} hosts believed they held the login "
            "lock — every winner opens its own browser window."
        )

    def test_exactly_one_racer_wins_when_collecting_a_dead_holder(self, tmp_path):
        """A stale lock must be collected once, not license a free-for-all."""
        lock = tmp_path / "session_host_user.lock"
        lock.write_text(json.dumps({"pid": 2**30, "timestamp": 0}))  # dead holder

        verdicts = _race_for_lock(tmp_path)

        assert sum(verdicts) == 1, f"{sum(verdicts)} racers collected the same stale lock"

    def test_nobody_steals_a_live_peers_fresh_lock(self, tmp_path):
        lock = tmp_path / "session_host_user.lock"
        lock.write_text(json.dumps({"pid": os.getpid(), "timestamp": 10.0}))

        with patch("servicenow_mcp.auth.auth_manager.time.time", return_value=11.0):
            verdicts = _race_for_lock(tmp_path)

        assert sum(verdicts) == 0

    def test_lock_survives_the_claim_and_names_its_holder(self, tmp_path):
        manager = _lock_manager(tmp_path)

        assert manager._acquire_login_lock() is True

        with open(manager._login_lock_path) as f:
            data = json.load(f)
        assert data["pid"] == os.getpid()
        assert data["timestamp"] > 0

    def test_lock_file_is_owner_only(self, tmp_path):
        """It names a pid, not a secret — but the cache dir holds credentials."""
        manager = _lock_manager(tmp_path)
        manager._acquire_login_lock()

        mode = stat.S_IMODE(os.stat(manager._login_lock_path).st_mode)
        assert mode & 0o077 == 0, f"lock file is group/world accessible: {oct(mode)}"

    def test_release_then_reacquire(self, tmp_path):
        manager = _lock_manager(tmp_path)
        assert manager._acquire_login_lock() is True
        manager._release_login_lock()
        assert not os.path.exists(manager._login_lock_path)
        assert manager._acquire_login_lock() is True

    def test_stale_corrupt_lock_is_collected_not_honored_forever(self, tmp_path):
        """Garbage from a holder that died mid-write must not block logins."""
        lock = tmp_path / "session_host_user.lock"
        lock.write_text("{ truncated")
        old = time.time() - AuthManager.LOGIN_LOCK_CLAIM_GRACE_SECONDS - 60
        os.utime(lock, (old, old))

        manager = _lock_manager(tmp_path)
        assert manager._acquire_login_lock() is True

    def test_a_lock_claimed_moments_ago_is_not_collected_as_corrupt(self, tmp_path):
        """The O_EXCL create and the payload write are two syscalls.

        A peer that just won the claim has an EMPTY lock file for a few
        microseconds. Reading that as "corrupt, collect it" is how two hosts
        both end up holding the lock and both open a browser window.
        """
        lock = tmp_path / "session_host_user.lock"
        lock.write_bytes(b"")  # exactly what O_EXCL leaves before the write lands

        manager = _lock_manager(tmp_path)
        assert manager._acquire_login_lock() is False

    def test_unwritable_lock_dir_fails_open(self, tmp_path):
        """A broken cache dir must not deadlock every host out of logging in."""
        manager = AuthManager.__new__(AuthManager)
        manager._login_lock_path = str(tmp_path / "no_such_dir" / "session.lock")

        assert manager._acquire_login_lock() is True  # fail open, don't deadlock


def _session_manager(tmp_path):
    manager = AuthManager.__new__(AuthManager)
    manager.config = MagicMock()
    manager.config.type = AuthType.BROWSER
    manager.instance_url = "https://example.service-now.com"
    manager._session_cache_path = str(tmp_path / "session_host_user.json")
    manager._browser_cookie_header = "JSESSIONID=abc; glide_user_route=xyz"
    manager._browser_user_agent = "Mozilla/5.0"
    manager._browser_session_token = "g_ck_value"
    manager._browser_cookie_expires_at = 9_999_999_999.0
    manager._browser_last_validated_at = 1.0
    manager._browser_last_login_at = 1.0
    manager._session_disk_hash = None
    manager._session_disk_mtime_ns = 0
    return manager


class TestSessionCacheWriteIsAtomic:
    def test_write_lands_complete_and_owner_only(self, tmp_path):
        manager = _session_manager(tmp_path)
        manager._save_session_to_disk()

        with open(manager._session_cache_path) as f:
            data = json.load(f)
        assert data["cookie_header"] == manager._browser_cookie_header
        assert data["session_token"] == "g_ck_value"

        mode = stat.S_IMODE(os.stat(manager._session_cache_path).st_mode)
        assert mode & 0o077 == 0, f"credential file is readable by others: {oct(mode)}"

    def test_a_failed_write_leaves_the_previous_session_intact(self, tmp_path):
        """The bug: O_TRUNC destroyed the old session before writing the new one.

        With a temp file + replace, a mid-write failure cannot damage the
        session every other host is still using.
        """
        manager = _session_manager(tmp_path)
        manager._save_session_to_disk()
        before = open(manager._session_cache_path).read()

        manager._browser_cookie_header = "JSESSIONID=new"
        manager._session_disk_hash = None  # force the write past the dedup check
        with patch("servicenow_mcp.auth.auth_manager.json.dump", side_effect=OSError("disk full")):
            manager._save_session_to_disk()  # must not raise

        assert open(manager._session_cache_path).read() == before

    def test_a_failed_write_leaves_no_credential_fragment(self, tmp_path):
        manager = _session_manager(tmp_path)
        with patch("servicenow_mcp.auth.auth_manager.json.dump", side_effect=OSError("disk full")):
            manager._save_session_to_disk()

        leftovers = [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
        assert leftovers == [], f"temp credential files left behind: {leftovers}"

    def test_replace_tightens_a_preexisting_world_readable_file(self, tmp_path):
        """A 0644 file from an older version must not survive the rewrite."""
        manager = _session_manager(tmp_path)
        with open(manager._session_cache_path, "w") as f:
            f.write("{}")
        os.chmod(manager._session_cache_path, 0o644)

        manager._save_session_to_disk()

        mode = stat.S_IMODE(os.stat(manager._session_cache_path).st_mode)
        assert mode & 0o077 == 0, f"stayed world-readable: {oct(mode)}"

    def test_concurrent_readers_never_see_a_torn_file(self, tmp_path):
        """Hammer the writer while readers parse: every read is valid JSON.

        The old in-place O_TRUNC write made this flaky by construction — the
        reader could open the file between truncate and dump.
        """
        manager = _session_manager(tmp_path)
        manager._save_session_to_disk()
        path = manager._session_cache_path
        stop = threading.Event()
        torn = []

        def _writer():
            for i in range(300):
                manager._browser_cookie_header = f"JSESSIONID={i}"
                manager._session_disk_hash = None  # defeat the dedup fast path
                manager._save_session_to_disk()
            stop.set()

        def _reader():
            while not stop.is_set():
                try:
                    with open(path) as f:
                        payload = json.load(f)
                    if "cookie_header" not in payload:
                        torn.append("missing key")
                except FileNotFoundError:
                    torn.append("file vanished mid-write")
                except json.JSONDecodeError:
                    torn.append("half-written JSON")

        threads = [threading.Thread(target=_writer)] + [
            threading.Thread(target=_reader) for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert torn == [], f"sibling read a torn session file: {torn[:5]}"


@pytest.mark.parametrize("method", ["_acquire_login_lock", "_save_session_to_disk"])
def test_no_in_place_truncating_write_returns(method):
    """Guard: neither path may go back to `open(path, "w")` on the live file."""
    import inspect

    source = inspect.getsource(getattr(AuthManager, method))
    assert 'open(self._login_lock_path, "w")' not in source
    assert 'open(self._session_cache_path, "w")' not in source


class TestSiblingUpdatesAreNeverMissed:
    """A sibling's token rotation must be adopted no matter how soon it lands.

    A 0.5 s tolerance window lived in `_maybe_adopt_sibling_session_update`
    until v1.19.11. Because the early return did not advance the watermark, a
    sibling write inside that window was skipped — and re-skipped on every later
    call, forever. The victim keeps sending a dead g_ck, gets 302'd to
    /logout_success.do, and re-auths in a loop: exactly what the function is for.
    """

    def test_rotation_landing_immediately_after_our_write_is_adopted(self, tmp_path):
        manager = _session_manager(tmp_path)
        manager.config.type = AuthType.BROWSER
        manager._save_session_to_disk()  # arms the watermark with OUR mtime

        # A sibling rotates the token and republishes — microseconds later, i.e.
        # deep inside the old tolerance window.
        payload = json.loads(open(manager._session_cache_path).read())
        payload["session_token"] = "SIBLING_ROTATED_g_ck"
        with open(manager._session_cache_path, "w") as f:
            json.dump(payload, f)

        adopted = manager._maybe_adopt_sibling_session_update()

        assert adopted is True, "sibling rotation inside the old 0.5s window was dropped"
        assert manager._browser_session_token == "SIBLING_ROTATED_g_ck"

    def test_a_skipped_check_still_advances_the_watermark(self, tmp_path):
        """The old early-return froze the watermark, so the miss was permanent."""
        manager = _session_manager(tmp_path)
        manager.config.type = AuthType.BROWSER
        manager._save_session_to_disk()

        manager._maybe_adopt_sibling_session_update()  # nothing new to adopt

        assert manager._session_disk_mtime_ns == os.stat(manager._session_cache_path).st_mtime_ns

    def test_unchanged_file_is_not_reparsed(self, tmp_path):
        """The fast path must survive the fix — get_headers calls this every time."""
        manager = _session_manager(tmp_path)
        manager.config.type = AuthType.BROWSER
        manager._save_session_to_disk()

        with patch.object(manager, "_reload_session_from_disk") as reload_spy:
            assert manager._maybe_adopt_sibling_session_update() is False
        reload_spy.assert_not_called()


class TestConcurrentWritersDoNotCorruptTheCache:
    def test_threads_in_one_process_do_not_share_a_temp_file(self, tmp_path):
        """Per-PID temp names are not enough: one host writes from many threads.

        Two threads opening the same temp path both write from offset 0; the
        longer one's tail survives under the shorter one's body, and os.replace
        then atomically publishes the malformed result.
        """
        manager = _session_manager(tmp_path)
        manager.config.type = AuthType.BROWSER
        errors = []

        def _writer(n):
            try:
                for i in range(60):
                    manager._browser_cookie_header = f"JSESSIONID={n}_{i}" + "x" * (n * 400)
                    manager._session_disk_hash = None  # defeat the dedup fast path
                    manager._save_session_to_disk()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(n,)) for n in range(1, 5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert errors == []
        with open(manager._session_cache_path) as f:
            payload = json.load(f)  # must be parseable, not interleaved garbage
        assert payload["cookie_header"].startswith("JSESSIONID=")
        leftovers = [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
        assert leftovers == [], f"temp files left behind: {leftovers}"


class TestInvalidateDoesNotEatASiblingsSession:
    def test_transient_read_failure_does_not_delete(self, tmp_path):
        """An OSError is not proof the file is ours — deleting on it is the bug.

        (Genuinely corrupt CONTENT is still removed; that invariant is pinned in
        test_auth_manager_browser.py::test_invalidate_deletes_disk_when_file_unreadable.)
        """
        manager = _session_manager(tmp_path)
        manager.config.type = AuthType.BROWSER
        manager._save_session_to_disk()
        path = manager._session_cache_path

        manager._needs_profile_cookie_purge = False
        manager._auth_event = MagicMock()
        with patch("servicenow_mcp.auth.auth_manager.open", side_effect=OSError("EMFILE")):
            manager.invalidate_browser_session()

        assert os.path.exists(path), "a transient read error deleted the session cache"

    def test_session_rewritten_while_we_looked_is_kept(self, tmp_path):
        """A sibling that finished a login mid-inspection must keep its session."""
        manager = _session_manager(tmp_path)
        manager.config.type = AuthType.BROWSER
        manager._save_session_to_disk()
        path = manager._session_cache_path
        manager._needs_profile_cookie_purge = False
        manager._auth_event = MagicMock()

        real_stat = os.stat
        calls = {"n": 0}

        def _stat_then_republish(target, *args, **kwargs):
            result = real_stat(target, *args, **kwargs)
            calls["n"] += 1
            if calls["n"] == 1 and str(target) == path:
                # Between our read and our delete, a sibling publishes a fresh
                # session at the same path.
                with open(path, "w") as f:
                    json.dump({"cookie_header": "FRESH=FROM_SIBLING"}, f)
                os.utime(path, ns=(result.st_mtime_ns + 10**9, result.st_mtime_ns + 10**9))
            return result

        with patch("servicenow_mcp.auth.auth_manager.os.stat", side_effect=_stat_then_republish):
            manager.invalidate_browser_session()

        assert os.path.exists(path), "deleted a session a sibling had just published"
        with open(path) as f:
            assert json.load(f)["cookie_header"] == "FRESH=FROM_SIBLING"
