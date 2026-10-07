"""A diff over the line budget is paged by hunk, never silently cut."""

from servicenow_mcp.utils.text_diff import paged_diff


def _bodies(changes):
    old = [f"line {i}" for i in range(2000)]
    new = list(old)
    for at in changes:
        new[at] = f"changed {at}"
    return "\n".join(old), "\n".join(new)


def test_a_small_diff_is_returned_whole():
    old, new = _bodies([10])
    out = paged_diff(old, new, old_label="a", new_label="b")
    assert "hunk_index" not in out
    assert (out["lines_added"], out["lines_removed"], out["hunks_total"]) == (1, 1, 1)


def test_a_large_diff_shows_whole_hunks_and_indexes_every_one():
    old, new = _bodies(range(100, 2000, 100))  # 19 separate hunks
    out = paged_diff(old, new, old_label="a", new_label="b", max_lines=40)

    assert out["hunks_total"] == 19
    assert len(out["hunk_index"]) == 19
    assert out["hunks_shown"] == [1, 2, 3, 4]  # 2 header lines + 9 per hunk
    assert (out["lines_added"], out["lines_removed"]) == (19, 19)  # whole diff, not the shown part
    assert "15 more hunk(s)" in out["more"]


def test_any_hunk_can_be_requested_whole():
    old, new = _bodies(range(100, 2000, 100))
    out = paged_diff(old, new, old_label="a", new_label="b", max_lines=40, hunk=19)
    assert out["hunk_shown"] == 19
    assert "+changed 1900" in out["diff"]


def test_a_hunk_that_does_not_exist_says_so():
    old, new = _bodies([10])
    out = paged_diff(old, new, old_label="a", new_label="b", hunk=5)
    assert "does not exist" in out["error"]
