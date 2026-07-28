"""Recognise the one thing a click in the shared window is not: server-side code.

The debug window costs one ``confirm`` to drive, which is the right price for
clicking Save — the record it creates is a record the Table API could have
created anyway. Background Scripts is not that. ``/sys.scripts.do`` runs
arbitrary server-side JavaScript in the signed-in session, outside ACLs, with no
record to point at afterwards; so do Fix Scripts, a scheduled job's Execute Now,
and an ATF run. Reached with ``fill`` + ``click``, all four used to cost exactly
what clicking Save costs — while ``eval``, which is strictly weaker because it
runs in the browser, cost two approvals. The price list was upside down.

So this module answers one question — "would this step RUN server-side code?" —
and the tools charge a second approval when the answer is yes.

Two axes, because either one alone has a hole:

``surface_for_url``   the page the window is ON. Checked against the LIVE
    ``page.url`` at each activating step rather than pre-flight, because a click
    that navigates to Background Scripts would otherwise be followed by a click
    on Run that no pre-flight ever saw.
``surface_for_step``  the selector or text the step NAMES. A Fix Script run from
    a list view's context menu never loads a form, so the URL says nothing and
    the verb says everything. Cheap enough to check before the browser is
    touched at all.

Opening these pages is deliberately NOT gated. Someone asking to look at
Background Scripts is asking to look; the window is on their screen and the
address bar is right there. Only running is a decision.
"""

from typing import Any, Dict, Optional
from urllib.parse import unquote

# Same shape as write_guards' publish-class double confirm: the tool's own
# confirm means "drive the page", this one means "run this on the server".
CONFIRM_FIELD = "confirm_script_exec"
CONFIRM_VALUE = "approve"

# Pages whose whole purpose is running code someone typed. Matched as a
# substring of the full URL so a nav_to.do wrapper (or any query string) still
# resolves to the surface it is wrapping.
_SURFACE_PATHS: Dict[str, str] = {
    "sys.scripts.do": "Background Scripts",
    "sys_script_fix.do": "Fix Script",
    "sysauto_script.do": "Scheduled Script Execution",
    "sys_atf_test.do": "ATF test",
    "sys_atf_test_suite.do": "ATF test suite",
}

# The UI actions that pull the trigger, by element name and by button label.
# A list-view context menu runs a Fix Script without ever loading its form, so
# the verb has to be recognisable on its own.
_RUN_VERBS: Dict[str, str] = {
    "runscript": "Background Scripts",
    "run script": "Background Scripts",
    "sysverb_run_fix": "Fix Script",
    "run fix script": "Fix Script",
    "sysverb_execute_now": "Scheduled Script Execution",
    "execute now": "Scheduled Script Execution",
    "sysverb_run_test": "ATF test",
    "run test": "ATF test",
}

# Steps that can pull a trigger. `fill` is not one of them: typing a script into
# a textarea runs nothing, and blocking it would stop the model from showing the
# user what it wants run — which is the outcome this gate is asking for.
ACTIVATING_ACTIONS = frozenset({"click", "double_click", "press"})


class ServerScriptBlocked(RuntimeError):
    """A batch was stopped because a step would have run server-side code."""

    def __init__(self, message: str, *, surface: str) -> None:
        super().__init__(message)
        self.surface = surface


def _haystack(*parts: Any) -> str:
    """Lowercased, percent-decoded text to substring-match against.

    Decoded because ``nav_to.do?uri=%2Fsys.scripts.do`` is the same destination
    as the plain path, and a gate that a URL encoder walks through is not a gate.
    """
    return " ".join(unquote(str(part or "")) for part in parts).lower()


def surface_for_url(url: Any) -> Optional[str]:
    """Name of the script-runner surface *url* points at, or None."""
    hay = _haystack(url)
    for path, surface in _SURFACE_PATHS.items():
        if path in hay:
            return surface
    return None


def surface_for_step(step: Dict[str, Any]) -> Optional[str]:
    """Name of the surface an activating step's selector/text names, or None.

    Independent of what page the window is on, which is the point: this is the
    half that survives a run invoked from a list view.
    """
    if step.get("action") not in ACTIVATING_ACTIONS:
        return None
    hay = _haystack(step.get("selector"), step.get("value"), step.get("key"))
    for verb, surface in _RUN_VERBS.items():
        if verb in hay:
            return surface
    return None


def surface_in_source(source: Any) -> Optional[str]:
    """Name of the surface a piece of JavaScript posts to, or None.

    ``fetch('/sys.scripts.do', {method:'POST'})`` is an eval that never loads the
    page and runs the script anyway. Substring matching is not proof against an
    author who splits the string deliberately — but the caller here is a model
    taking the short path, not an adversary, and the short path is literal.
    """
    return surface_for_url(source)


def approved(value: Any) -> bool:
    """True when the caller supplied the second approval."""
    return str(value or "").strip().lower() == CONFIRM_VALUE


def rejection(surface: str, *, steps: Any = None) -> str:
    """The stop text. One message, so the tool layer and the live per-step check
    stop in the same words.

    Phrased as a door rather than a wall: this is a capability the window HAS,
    and the second approval is not a veto — it is the record that the person
    watching the screen saw the script before it ran. So the message says what
    is missing and hands back the exact retry, the way the publish-class
    rejections in write_guards do.
    """
    where = f"Step(s) {steps} would" if steps else "This would"
    return (
        f"{where} RUN a server-side script ({surface}) in the signed-in session. "
        "That is allowed, deliberately — show the user the exact script body "
        f"first, then retry with {CONFIRM_FIELD}='{CONFIRM_VALUE}' alongside "
        "confirm. It executes with their full server-side privileges and outside "
        "ACLs, so 'they have seen it' is the whole point of the second approval."
    )


__all__ = [
    "ACTIVATING_ACTIONS",
    "CONFIRM_FIELD",
    "CONFIRM_VALUE",
    "ServerScriptBlocked",
    "approved",
    "rejection",
    "surface_for_step",
    "surface_for_url",
    "surface_in_source",
]
