"""Does the window still ANSWER — not just exist?

`window_liveness` reads process, port and tab count. A window can pass all
three and still be useless: the browser process serves CDP while the tab's
renderer is frozen, and every call into it then waits out a 60-120s offload
timeout before failing — after which the next call reuses the same window and
waits again. Nothing ever opened a fresh one, because by every signal that was
read the window was fine.

So a reused window is asked to run `1` in its instance tabs. The answer is
three-valued on purpose:

- True  — it answered.
- False — it did NOT answer, twice in a row, within PROBE_TIMEOUT_S each. Only
  this one may lead to a restart. Two misses, not one: a tab committing a slow
  ServiceNow navigation can hold its JS context for a few seconds, and killing a
  healthy window over one slow page is worse than waiting once more.
- None  — the question could not be asked (no instance tab, no Playwright, the
  connection failed some other way). Never treated as "hung": an unasked
  question is not a negative answer.
"""

import logging
from typing import Any, List, Optional

from ._offload import cdp_browser, run_off_loop
from .capture import _on_instance
from .window import WindowState

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 6.0
PROBE_ATTEMPTS = 2


def _instance_pages(browser: Any, instance_host: str) -> List[Any]:
    return [
        page
        for context in browser.contexts
        for page in context.pages
        if not str(getattr(page, "url", "")).startswith("devtools://")
        and _on_instance(page, instance_host)
    ]


def _probe_once(state: WindowState) -> Optional[bool]:
    def _work() -> Optional[bool]:
        with cdp_browser(state.cdp_endpoint) as browser:
            pages = _instance_pages(browser, state.instance_host)
            if not pages:
                return None
            for page in pages:
                page.evaluate("1")
            return True

    try:
        return run_off_loop(_work, timeout_s=PROBE_TIMEOUT_S)
    except TimeoutError:
        # The offload worker is poisoned on a timeout, so the next attempt runs
        # on a fresh thread and a fresh connection — a genuine second ask.
        return False
    except Exception as exc:  # noqa: BLE001 - any other failure is "could not ask"
        logger.debug("Debug window responsiveness probe could not run: %s", exc)
        return None


def window_answers(state: WindowState) -> Optional[bool]:
    """True / False (hung: PROBE_ATTEMPTS misses in a row) / None (not asked)."""
    for _ in range(PROBE_ATTEMPTS):
        answer = _probe_once(state)
        if answer is not False:
            return answer
    return False


__all__ = ["PROBE_ATTEMPTS", "PROBE_TIMEOUT_S", "window_answers"]
