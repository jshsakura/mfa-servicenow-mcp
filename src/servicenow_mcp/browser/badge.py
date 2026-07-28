"""An on-screen label so the user always knows WHICH window this is.

With a dev window and a test window open side by side, "check the errors on
that page" is ambiguous — and acting on the wrong instance is the failure this
repo guards against everywhere else. The badge answers it at a glance.

Two constraints shape the implementation, both from the feature's own purpose:

- This window is used to debug CSS. The badge must therefore be invisible to
  the page's styles and contribute nothing to layout: it lives in a CLOSED
  shadow root on ``documentElement`` (so no page selector can reach it) and is
  ``position: fixed`` with ``pointer-events: none``.
- Screenshots are used to judge visual breakage, so the badge must not appear
  in them. :func:`hide_badge_script` / :func:`show_badge_script` bracket every
  capture.
"""

import os
from typing import Any

from ..utils.instances import ACTIVE_INSTANCE_ENV

BADGE_ELEMENT_ID = "__sn_mcp_debug_badge__"

# The signed-in user is read in the page, not passed in from Python, and that
# is the point: this window has its OWN ServiceNow session. A name captured
# when the script was built would go stale the moment someone impersonates —
# which is exactly the moment the badge needs to be right.
_USER_RESOLVER = """
  const resolveUser = () => {
    try { if (window.NOW && NOW.user && NOW.user.userName) return String(NOW.user.userName); } catch (e) {}
    try { if (window.g_user && g_user.userName) return String(g_user.userName); } catch (e) {}
    try { if (window.NOW && NOW.user_name) return String(NOW.user_name); } catch (e) {}
    return '';
  };
  // The globals land well after DOMContentLoaded on Next Experience and the
  // portal, so a single read at mount would almost always come up empty.
  // Polling stops once a name appears: an impersonation reloads the page, and
  // this whole script runs again on the new document.
  const trackUser = (sep, userEl) => {
    let tries = 0;
    const tick = () => {
      const user = resolveUser();
      if (user) {
        userEl.textContent = user;
        sep.style.display = '';
        userEl.style.display = '';
        return;
      }
      if (++tries < 40) setTimeout(tick, 500);
    };
    tick();
  };
"""

# Re-injected on every navigation via add_init_script, so the label survives
# the user clicking through the portal.
_BADGE_TEMPLATE = """
(() => {
  const HOST_ID = %(host_id)s;
  const PROFILE = %(label)s;
  const ACCENT = %(accent)s;
  if (window[HOST_ID]) return;

%(user_script)s

  const mount = () => {
    const root = document.documentElement;
    if (!root) return;
    const host = document.createElement('div');
    host.setAttribute('data-sn-mcp-badge', '1');
    // Closed mode: page scripts cannot reach in, page CSS cannot select in.
    const shadow = host.attachShadow({ mode: 'closed' });

    const wrap = document.createElement('div');
    wrap.style.cssText = [
      'position:fixed', 'right:10px', 'bottom:10px', 'z-index:2147483647',
      'display:flex', 'align-items:center', 'gap:7px',
      'padding:5px 11px 5px 9px', 'border-radius:999px',
      // Glass rather than a flat slab: it sits over live UI all day, so it
      // should read as an overlay and not as part of the page being debugged.
      'background:rgba(18,18,20,.78)', '-webkit-backdrop-filter:blur(8px)',
      'backdrop-filter:blur(8px)',
      'border:1px solid rgba(255,255,255,.10)',
      'box-shadow:0 2px 10px rgba(0,0,0,.32)',
      'font:500 11px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace',
      'letter-spacing:.01em',
      'pointer-events:none', 'user-select:none',
      'opacity:0', 'transition:opacity .25s ease'
    ].join(';');

    // The dot carries the profile identity as COLOR, which is the part you
    // register without reading — the whole point when the mistake being
    // guarded against is "I thought this window was dev".
    const dot = document.createElement('span');
    dot.style.cssText = [
      'width:7px', 'height:7px', 'border-radius:50%%', 'flex:none',
      'background:' + ACCENT,
      'box-shadow:0 0 0 2px ' + ACCENT + '33'
    ].join(';');

    const text = document.createElement('span');
    text.style.cssText = 'color:#e9e9ec;white-space:nowrap';
    text.textContent = PROFILE;

    // Hidden until a user actually resolves, so the badge never shows a
    // dangling separator on a page that has no ServiceNow session yet.
    const sep = document.createElement('span');
    sep.style.cssText = 'color:rgba(255,255,255,.22);display:none';
    sep.textContent = '|';

    const userEl = document.createElement('span');
    userEl.style.cssText = 'color:rgba(233,233,236,.62);white-space:nowrap;display:none';

    wrap.appendChild(dot);
    wrap.appendChild(text);
    wrap.appendChild(sep);
    wrap.appendChild(userEl);
    shadow.appendChild(wrap);
    root.appendChild(host);
    requestAnimationFrame(() => { wrap.style.opacity = '1'; });

    window[HOST_ID] = { host, badge: text, user: userEl };
    trackUser(sep, userEl);
  };

  if (document.documentElement) mount();
  else document.addEventListener('DOMContentLoaded', mount, { once: true });
})();
"""

_TOGGLE_TEMPLATE = """
(() => {
  const ref = window[%(host_id)s];
  if (ref && ref.host) ref.host.style.display = %(display)s;
})();
"""


def _js_string(value: str) -> str:
    """Minimal JS string literal escaping for values we interpolate."""
    escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
    return f"'{escaped}'"


def profile_label(config: Any = None) -> str:
    """Which MCP profile this window belongs to.

    The named-instance alias is the thing a person actually calls the profile
    ("dev", "test", "prod") and the thing they switch between. In single-
    instance mode there is no alias, so the account carries the identity on its
    own and this stays 'default' — matching what the server reports.
    """
    alias = (os.environ.get(ACTIVE_INSTANCE_ENV) or "").strip()
    if alias:
        return alias
    return "default"


def badge_label(profile: str) -> str:
    """Short, scannable identity. The ACCOUNT is appended in-page, live.

    Deliberately no URL: the address bar is directly above the badge, so
    repeating it spends the badge's whole width on the one fact already on
    screen. What is NOT on screen is which profile this window belongs to and
    who it is signed in as — and the second one matters most, because this
    window has its own session and may well be a different user (or an
    impersonation) than the API tools are running as.
    """
    return f"MCP DEBUG · {profile}" if profile else "MCP DEBUG"


# Environment colours, in the order everyone already expects from CI badges and
# deploy dashboards. Matched on the profile name because that is what the
# person named — an instance called "prod-eu" is production whatever its URL.
_ACCENTS = (
    (("prod", "production", "live"), "#ff4d4f"),
    (("stage", "staging", "uat", "preprod", "pre-prod"), "#ffa940"),
    (("test", "qa", "sit"), "#ffd666"),
    (("dev", "develop", "development", "sandbox", "local"), "#4ade80"),
)
_ACCENT_FALLBACK = "#60a5fa"


def badge_accent(profile: str) -> str:
    """A colour for the profile dot: red for prod, down to green for dev.

    Anything unrecognized gets one neutral blue rather than a hashed colour —
    a made-up hue would read as meaningful and it is not. The one signal that
    must never be ambiguous is "this is production".
    """
    name = (profile or "").strip().lower()
    for keywords, colour in _ACCENTS:
        if any(word in name for word in keywords):
            return colour
    return _ACCENT_FALLBACK


def badge_init_script(profile: str) -> str:
    return _BADGE_TEMPLATE % {
        "host_id": _js_string(BADGE_ELEMENT_ID),
        "label": _js_string(badge_label(profile)),
        "accent": _js_string(badge_accent(profile)),
        "user_script": _USER_RESOLVER,
    }


def hide_badge_script() -> str:
    """Hide the badge so it never lands in a screenshot."""
    return _TOGGLE_TEMPLATE % {"host_id": _js_string(BADGE_ELEMENT_ID), "display": "'none'"}


def show_badge_script() -> str:
    return _TOGGLE_TEMPLATE % {"host_id": _js_string(BADGE_ELEMENT_ID), "display": "''"}


__all__ = [
    "BADGE_ELEMENT_ID",
    "badge_init_script",
    "badge_label",
    "hide_badge_script",
    "show_badge_script",
]
