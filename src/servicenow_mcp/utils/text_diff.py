"""Unified diffs that page by hunk instead of being cut off.

A diff clipped at a line budget hides whatever sits past the cut, and the
caller cannot ask for it: the old renderers appended "[DIFF TRUNCATED]" and
stopped, so a 67 KB body that differed deep inside was compared by hand. Here
the budget decides how much is SHOWN, never what is KNOWN — every hunk is
indexed (position + counts), totals come from the whole diff, and any hunk
can be requested by number.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional


def _split_hunks(diff_lines: List[str]) -> tuple[List[str], List[List[str]]]:
    header: List[str] = []
    hunks: List[List[str]] = []
    for line in diff_lines:
        if line.startswith("@@"):
            hunks.append([line])
        elif hunks:
            hunks[-1].append(line)
        else:
            header.append(line)
    return header, hunks


def _counts(hunk: List[str]) -> tuple[int, int]:
    added = sum(1 for line in hunk[1:] if line.startswith("+"))
    removed = sum(1 for line in hunk[1:] if line.startswith("-"))
    return added, removed


def paged_diff(
    old: str,
    new: str,
    *,
    old_label: str,
    new_label: str,
    context_lines: int = 3,
    max_lines: int = 120,
    hunk: Optional[int] = None,
    more_hint: str = "",
) -> Dict[str, Any]:
    """Diff ``old`` -> ``new``: whole when it fits, else whole hunks + an index.

    ``lines_added`` / ``lines_removed`` / ``hunks_total`` always describe the
    WHOLE diff. ``hunk=n`` (1-based) returns just that hunk, uncut.
    """
    diff_lines = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=old_label,
            tofile=new_label,
            lineterm="",
            n=context_lines,
        )
    )
    header, hunks = _split_hunks(diff_lines)
    added = removed = 0
    index: List[Dict[str, Any]] = []
    for number, body in enumerate(hunks, 1):
        a, r = _counts(body)
        added += a
        removed += r
        index.append({"hunk": number, "at": body[0], "added": a, "removed": r})
    out: Dict[str, Any] = {
        "lines_added": added,
        "lines_removed": removed,
        "hunks_total": len(hunks),
    }

    if hunk is not None:
        if not 1 <= hunk <= len(hunks):
            out["error"] = f"hunk {hunk} does not exist; this diff has {len(hunks)} hunk(s)."
            out["hunk_index"] = index
            return out
        out["diff"] = "\n".join(header + hunks[hunk - 1])
        out["hunk_shown"] = hunk
        return out

    if len(diff_lines) <= max_lines:
        out["diff"] = "\n".join(diff_lines)
        return out

    shown: List[str] = list(header)
    shown_numbers: List[int] = []
    for number, body in enumerate(hunks, 1):
        if shown_numbers and len(shown) + len(body) > max_lines:
            break
        if not shown_numbers and len(shown) + len(body) > max_lines:
            # A single hunk larger than the budget: show its head and say so.
            room = max(max_lines - len(shown), 1)
            shown += body[:room] + [
                f"... [hunk {number}: {len(body) - room} more line(s) — request hunk={number}]"
            ]
        else:
            shown += body
        shown_numbers.append(number)
    out["diff"] = "\n".join(shown)
    out["hunks_shown"] = shown_numbers
    out["hunk_index"] = index
    hidden = len(hunks) - len(shown_numbers)
    out["more"] = (
        f"{hidden} more hunk(s) not shown (see hunk_index for where and how big). "
        f"Request one with hunk=<n>{more_hint}."
        if hidden
        else f"The shown hunk was cut for length; request it whole with hunk=<n>{more_hint}."
    )
    return out
