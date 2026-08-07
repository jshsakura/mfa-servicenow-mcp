"""The debug window's scratch dir has a ceiling now, and a floor under it.

The floor is the load-bearing half. Artifact paths are RETURNED to the caller —
a response says `screenshot: /…/shot-1786064130354.webp` and the model may read
it back several turns later. A prune that only knew about age would delete files
whose paths are live in someone's context, and it would look like the tool lying
about where it put something.
"""

import os
import time

from servicenow_mcp.browser.artifacts import KEEP_RECENT, prune


def _fill(directory, count, *, size=1024, age_s=0.0, prefix="shot-", suffix=".webp"):
    """`count` artifacts, oldest first, each `age_s` older than the last."""
    now = time.time()
    made = []
    for index in range(count):
        path = os.path.join(directory, f"{prefix}{index:04d}{suffix}")
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        stamp = now - (count - index) * age_s
        os.utime(path, (stamp, stamp))
        made.append(path)
    return made


def test_a_directory_inside_its_budget_is_left_alone(tmp_path):
    _fill(str(tmp_path), 5)

    assert prune(str(tmp_path)) == {}
    assert len(os.listdir(tmp_path)) == 5


def test_the_oldest_go_first_once_over_budget(tmp_path):
    made = _fill(str(tmp_path), 60, size=4096, age_s=3600)

    result = prune(str(tmp_path), max_bytes=100 * 1024, keep_recent=10, min_age_s=0)

    assert result["artifacts_pruned"] > 0
    assert not os.path.exists(made[0]), "the oldest went"
    assert os.path.exists(made[-1]), "the newest stayed"


def test_the_most_recent_are_never_removed_however_tight_the_budget(tmp_path):
    """Their paths are live in the caller's context. This is the whole point."""
    made = _fill(str(tmp_path), 30, size=1024 * 1024, age_s=86400)

    prune(str(tmp_path), max_bytes=1, keep_recent=10, min_age_s=0)

    survivors = set(os.listdir(tmp_path))
    for path in made[-10:]:
        assert os.path.basename(path) in survivors


def test_a_recent_file_past_the_count_floor_is_still_too_young(tmp_path):
    """A capture from a minute ago belongs to the conversation happening now."""
    made = _fill(str(tmp_path), 30, size=1024 * 1024, age_s=1.0)

    result = prune(str(tmp_path), max_bytes=1, keep_recent=2, min_age_s=600)

    assert "artifacts_pruned" not in result
    assert all(os.path.exists(path) for path in made)


def test_over_budget_with_nothing_eligible_says_so(tmp_path):
    """A cap that silently gave up looks exactly like one that worked."""
    _fill(str(tmp_path), 5, size=4 * 1024 * 1024, age_s=1.0)

    result = prune(str(tmp_path), max_bytes=1024, keep_recent=2, min_age_s=600)

    assert "artifacts_note" in result
    assert "nothing was old enough" in result["artifacts_note"]


def test_only_this_packages_files_are_touched(tmp_path):
    """A directory is not a licence to delete whatever is in it."""
    _fill(str(tmp_path), 40, size=1024 * 1024, age_s=86400)
    stranger = tmp_path / "notes.txt"
    stranger.write_text("someone put this here", encoding="utf-8")
    also = tmp_path / "shot-keep.tar"
    also.write_bytes(b"not an artifact")

    prune(str(tmp_path), max_bytes=1, keep_recent=0, min_age_s=0)

    assert stranger.exists()
    assert also.exists()


def test_both_artifact_kinds_are_counted_together(tmp_path):
    _fill(str(tmp_path), 20, size=1024 * 1024, age_s=86400, prefix="shot-", suffix=".webp")
    _fill(str(tmp_path), 20, size=1024 * 1024, age_s=86400, prefix="events-", suffix=".json")

    result = prune(str(tmp_path), max_bytes=4 * 1024 * 1024, keep_recent=4, min_age_s=0)

    assert result["artifacts_pruned"] > 0
    assert result["artifacts_freed_mb"] > 0


def test_a_missing_directory_is_not_an_error(tmp_path):
    assert prune(str(tmp_path / "never-created")) == {}


def test_the_default_floor_is_generous_enough_to_outlive_a_conversation():
    """A session holds a handful of paths at once, not dozens."""
    assert KEEP_RECENT >= 20
