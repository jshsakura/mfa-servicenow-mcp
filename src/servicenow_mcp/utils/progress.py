"""Per-call progress reporting for long-running tools (perceived speed).

Long data tools (e.g. ``download_app_sources``) would otherwise run silent for
tens of seconds and then dump everything at once. This module lets a tool body
emit incremental progress without changing its signature: the server installs a
per-call emitter via :func:`use_progress_emitter`, and the tool calls
:func:`emit_progress` at natural milestones.

Design invariants:
- **Zero behaviour change when nobody subscribed.** With no emitter installed,
  :func:`emit_progress` is a cheap no-op (the common case — most clients/calls
  do not request progress).
- **Best-effort, never fatal.** A failing emitter (dead notification socket,
  etc.) must never break the actual tool — errors are swallowed and logged at
  debug level only.
- **Context-scoped.** The emitter lives in a :class:`contextvars.ContextVar`, so
  concurrent calls never see each other's emitter and it is restored on exit.
"""

import contextlib
import contextvars
import logging
from typing import Callable, Iterator, Optional

logger = logging.getLogger(__name__)

# Emitter signature: (progress, total_or_None, message) -> None
ProgressEmitter = Callable[[float, Optional[float], str], None]

_emitter: contextvars.ContextVar[Optional[ProgressEmitter]] = contextvars.ContextVar(
    "sn_progress_emitter", default=None
)


def emit_progress(progress: float, total: Optional[float], message: str) -> None:
    """Report progress for the current call if an emitter is installed; else no-op.

    Never raises: progress is advisory and must not break the tool body.
    """
    fn = _emitter.get()
    if fn is None:
        return
    try:
        fn(float(progress), None if total is None else float(total), str(message))
    except Exception:  # noqa: BLE001 - progress must never break the tool
        logger.debug("progress emitter raised; ignoring", exc_info=True)


@contextlib.contextmanager
def use_progress_emitter(fn: Optional[ProgressEmitter]) -> Iterator[None]:
    """Install ``fn`` as the current-call progress emitter for the block's duration.

    Restores the previous emitter on exit (supports nesting). Passing ``None``
    explicitly silences progress for the block.
    """
    token = _emitter.set(fn)
    try:
        yield
    finally:
        _emitter.reset(token)
