"""Atomic local file writes.

Source downloads write thousands of files and may be interrupted (Ctrl-C, the
MCP server restarting, a background job's process dying). A plain
``Path.write_text`` truncates the target the instant it opens it, so an
interrupted write leaves a half-written file. That is dangerous here because
resume-skip trusts a file's mere *existence* — a truncated file would be kept
silently and never re-fetched.

``atomic_write_text`` writes to a sibling temp file and then ``os.replace``s it
into place. ``os.replace`` is atomic on the same filesystem, so an interrupted
write leaves either the complete prior file or the complete new one — never a
torn mix. (Durability across a hard power-loss would additionally need an
fsync per file; we skip that deliberately — it would cost an fsync on every one
of thousands of files, and resume simply re-fetches anything a power-loss
dropped. The invariant we need is "never truncated", which os.replace gives.)
"""

import os
import threading
from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically (temp file + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique per process+thread so concurrent writers never collide on the temp.
    tmp = path.parent / f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding=encoding) as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        # os.replace consumed tmp on success; only the failure path leaves it.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
