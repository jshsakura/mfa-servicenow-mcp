"""An on-screen label so the user always knows WHICH window this is.

With a dev window and a test window open side by side, "check the errors on
that page" is ambiguous — and acting on the wrong instance is the failure this
repo guards against everywhere else. The badge answers it at a glance.

Three constraints shape the implementation, all from the feature's own purpose:

- This window is used to debug CSS. The badge must therefore be invisible to
  the page's styles and contribute nothing to layout: it lives in a CLOSED
  shadow root on ``documentElement`` (so no page selector can reach it) and is
  ``position: fixed``. Its children stay inert; only the pill itself takes
  clicks, so it can be collapsed to a dot when it covers the element under
  investigation — which is the alternative to it being dismissed for good.
- Screenshots are used to judge visual breakage, so the badge must not appear
  in them. :func:`hide_badge_script` / :func:`show_badge_script` bracket every
  capture.
- It has to be there EVERY time, or the question it answers gets asked at the
  moment it is missing. It re-appends itself after the framework re-renders the
  document, and it is re-injected on every attach.
"""

import os
from typing import Any

from ..utils.instances import ACTIVE_INSTANCE_ENV

BADGE_ELEMENT_ID = "__sn_mcp_debug_badge__"

# Where the collapsed choice is remembered. localStorage rather than a Python
# file: it is a per-screen preference of the person looking at the window, and
# it has to survive the reloads a save or an impersonation causes without a
# round trip through the server.
COLLAPSED_KEY = "__sn_mcp_debug_badge_collapsed__"

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
  //
  // ACCOUNT is the user this window SIGNED IN as. Anyone else on screen is an
  // impersonation — including one done by hand through the avatar menu — so the
  // badge shows both names and colours them, rather than quietly swapping one
  // name for another and letting the ACLs of a different user look like a bug.
  const trackUser = (sep, userEl, paint) => {
    let tries = 0;
    const tick = () => {
      const user = resolveUser();
      if (user) {
        const acting = ACCOUNT && user.toLowerCase() !== ACCOUNT.toLowerCase();
        userEl.textContent = acting ? (ACCOUNT + ' \\u2192 ' + user) : user;
        userEl.style.color = acting ? IMPERSONATING : NORMAL_USER;
        userEl.style.fontWeight = acting ? '700' : '500';
        // paint() decides visibility, so a name arriving while the badge is
        // collapsed does not pop it back open behind the user's decision.
        paint();
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
  const PREFIX = %(prefix)s;
  const PROFILE_NAME = %(profile_name)s;
  const ACCENT = %(accent)s;
  const IDLE = %(idle)s;
  const ACCOUNT = %(account)s;
  const IMPERSONATING = %(impersonating)s;
  const NORMAL_USER = 'rgba(233,233,236,.62)';
  const COLLAPSED_KEY = %(collapsed_key)s;
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
      // Clickable, unlike everything else here — the badge is the one thing on
      // this overlay a person needs to operate (collapse it when it sits on top
      // of the element being debugged). It is small and in the corner, so the
      // page keeps effectively all of its own clicks.
      'pointer-events:auto', 'user-select:none', 'cursor:pointer',
      'opacity:0', 'transition:opacity .25s ease,padding .15s ease'
    ].join(';');
    wrap.title = 'MCP debug badge — click to collapse';

    const style = document.createElement('style');
    style.textContent =
      '@keyframes snmcp-pulse{0%%,100%%{opacity:1;transform:scale(1)}' +
      '50%%{opacity:.3;transform:scale(.75)}}';
    shadow.appendChild(style);

    // Two signals, two channels, so neither has to be given up:
    //   the RING is the environment and never changes — "I thought this window
    //   was dev" is the mistake it exists to prevent, and that mistake is made
    //   while nothing is happening.
    //   the FILL is activity — grey at rest, environment-coloured and pulsing
    //   while the MCP is attached and driving. Watching the window together,
    //   the question is constantly "was that me or the model?".
    const dot = document.createElement('span');
    dot.style.cssText = [
      'width:7px', 'height:7px', 'border-radius:50%%', 'flex:none',
      'background:' + IDLE,
      'box-shadow:0 0 0 2px ' + ACCENT + '55',
      'transition:background .2s ease'
    ].join(';');

    let idleTimer = null;
    const setActive = (on) => {
      if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
      if (on) {
        dot.style.background = ACCENT;
        dot.style.animation = 'snmcp-pulse 1s ease-in-out infinite';
        // Never leave it stuck lit: a tool call that dies mid-flight would
        // otherwise pulse forever and the light would stop meaning anything.
        idleTimer = setTimeout(() => setActive(false), %(active_ttl_ms)d);
      } else {
        dot.style.background = IDLE;
        dot.style.animation = '';
      }
    };

    // The profile NAME carries the colour, not the whole label. "MCP DEBUG" is
    // the same on every window, so colouring it would spend the badge's only
    // strong signal on the one word that never distinguishes anything — and at
    // 11px a fully tinted pill reads as decoration rather than as an answer.
    // Dimming the constant part also lets the name win the glance on its own.
    const text = document.createElement('span');
    text.style.cssText = 'color:rgba(233,233,236,.5);white-space:nowrap';
    text.textContent = PROFILE_NAME ? PREFIX + ' \\u00b7 ' : PREFIX;

    const nameEl = document.createElement('span');
    nameEl.style.cssText =
      'color:' + ACCENT + ';white-space:nowrap;font-weight:700;display:' +
      (PROFILE_NAME ? '' : 'none');
    nameEl.textContent = PROFILE_NAME;

    // Hidden until a user actually resolves, so the badge never shows a
    // dangling separator on a page that has no ServiceNow session yet.
    const sep = document.createElement('span');
    sep.style.cssText = 'color:rgba(255,255,255,.22);display:none';
    sep.textContent = '|';

    const userEl = document.createElement('span');
    userEl.style.cssText = 'color:' + NORMAL_USER + ';white-space:nowrap;display:none';

    wrap.appendChild(dot);
    wrap.appendChild(text);
    wrap.appendChild(nameEl);
    wrap.appendChild(sep);
    wrap.appendChild(userEl);
    shadow.appendChild(wrap);
    root.appendChild(host);
    requestAnimationFrame(() => { wrap.style.opacity = '1'; });

    // Collapsed is a dot, not a hidden badge: the environment ring and the
    // activity pulse — the two things you must not have to ask about — survive
    // in 7 pixels. Only the names fold away.
    let collapsed = false;
    const paint = () => {
      text.style.display = collapsed ? 'none' : '';
      nameEl.style.display = collapsed || !PROFILE_NAME ? 'none' : '';
      sep.style.display = collapsed || !userEl.textContent ? 'none' : '';
      userEl.style.display = collapsed || !userEl.textContent ? 'none' : '';
      wrap.style.padding = collapsed ? '6px' : '5px 11px 5px 9px';
      wrap.title = collapsed
        ? 'MCP debug badge — click to expand'
        : 'MCP debug badge — click to collapse';
    };
    const setCollapsed = (on) => {
      collapsed = !!on;
      paint();
      // Remembered per profile+origin, so collapsing it once survives the
      // reloads an impersonation and a save both cause. A storage that throws
      // (sandboxed document) simply means it reopens expanded.
      try { localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0'); } catch (e) {}
    };
    wrap.addEventListener('click', (event) => {
      event.stopPropagation();
      setCollapsed(!collapsed);
    });
    try { collapsed = localStorage.getItem(COLLAPSED_KEY) === '1'; } catch (e) {}
    paint();

    window[HOST_ID] = { host, badge: text, user: userEl, setActive, setCollapsed, paint };
    trackUser(sep, userEl, paint);

    // Stay up. A badge that is there only sometimes is worse than none: the
    // question it answers ("which window is this, and who am I here?") gets
    // asked precisely when it has quietly gone missing. ServiceNow's own
    // frameworks re-render large parts of the document — a workspace route
    // change, a portal page swap — and anything hanging off documentElement can
    // go with them. Re-appending is cheap and the element is inert
    // (pointer-events:none, closed shadow root), so it cannot come back as
    // something the page has to cope with.
    setInterval(() => {
      const root = document.documentElement;
      if (root && !root.contains(host)) root.appendChild(host);
    }, %(keepalive_ms)d);
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


# The constant half of the label. Split out because the badge draws the two
# halves differently — this one dimmed, the profile name in its colour — while
# badge_label still composes them for anywhere that wants the plain string.
BADGE_PREFIX = "MCP DEBUG"


def badge_label(profile: str) -> str:
    """Short, scannable identity. The ACCOUNT is appended in-page, live.

    Deliberately no URL: the address bar is directly above the badge, so
    repeating it spends the badge's whole width on the one fact already on
    screen. What is NOT on screen is which profile this window belongs to and
    who it is signed in as — and the second one matters most, because this
    window has its own session and may well be a different user (or an
    impersonation) than the API tools are running as.
    """
    return f"{BADGE_PREFIX} · {profile}" if profile else BADGE_PREFIX


# Distinct hues, all legible on the badge's near-black glass. Curated rather
# than generated: a hue computed from a hash lands wherever it lands, and half
# of the wheel is muddy or invisible at 11px against this background. Fourteen
# is enough that two profiles colliding is uncommon, and a collision costs
# nothing anyway — see badge_accent.
_PALETTE = (
    "#ff4d4f",  # red
    "#fb7185",  # rose
    "#f472b6",  # pink
    "#e879f9",  # fuchsia
    "#a78bfa",  # violet
    "#818cf8",  # indigo
    "#60a5fa",  # blue
    "#22d3ee",  # cyan
    "#2dd4bf",  # teal
    "#34d399",  # emerald
    "#4ade80",  # green
    "#a3e635",  # lime
    "#ffd666",  # amber
    "#ffa940",  # orange
)

# At rest the dot is a neutral grey, so the pulse reads as "something is
# happening NOW" rather than as decoration. The environment stays legible
# through the ring around it, which never changes.
IDLE_COLOUR = "#6b7280"

# Amber, the same "you are not in the normal state" colour the staging accent
# uses. Not red: impersonating is a thing you do on purpose, not an alarm.
IMPERSONATING_COLOUR = "#ffc53d"

# How often the badge checks it is still in the document. Long enough to be
# invisible on a profile, short enough that a re-render never leaves the window
# unlabelled for longer than a glance.
KEEPALIVE_MS = 2000

# A tool call that dies mid-flight must not leave the dot pulsing forever — a
# light that is always on stops being a light. The page reverts on its own.
ACTIVE_TTL_S = 30.0

_ACTIVITY_TEMPLATE = """
(() => {
  const ref = window[%(host_id)s];
  if (ref && ref.setActive) ref.setActive(%(state)s);
})();
"""


def badge_accent(profile: str) -> str:
    """A colour derived from the profile name. Same name, same colour, always.

    Colour is an IDENTITY channel here, not a severity one: it answers "is this
    the same window I was looking at a minute ago?" at a glance, across however
    many are open. It deliberately carries no meaning of its own — the meaning
    is in the label right next to it, which spells the profile out in words.

    This replaced a keyword table (prod→red, dev→green, everything else→one
    blue). Profile names are whatever the person configuring them chose, so
    "everything else" was the normal case, and every custom profile came out the
    same blue — the exact question the badge exists to answer, unanswered. A
    table cannot enumerate names it has never seen; a hash does not have to.

    Nothing is reserved, including red. A reserved colour would only be worth
    the complexity if colour were load-bearing for "this is production", and it
    is not: the badge writes the profile name, so a window called ``prod`` says
    so in text whatever colour it drew.

    FNV-1a, the same hash the probe uses, so the two agree on what stable and
    cheap means. Collisions are possible and harmless — two windows sharing a
    hue still carry different names beside it.
    """
    name = (profile or "").strip().lower()
    digest = 0x811C9DC5
    for char in name:
        digest ^= ord(char)
        digest = (digest * 0x01000193) & 0xFFFFFFFF
    return _PALETTE[digest % len(_PALETTE)]


def badge_init_script(profile: str, account: str = "") -> str:
    """The badge for this window.

    ``account`` is the user the window signed in as, when the server knows it.
    Anyone else showing up in the page is an impersonation and is drawn as
    ``account → impersonated`` in amber. Left empty (an OAuth or API-key profile
    has no browser username to compare against) the badge just names whoever is
    signed in, as before.
    """
    return _BADGE_TEMPLATE % {
        "host_id": _js_string(BADGE_ELEMENT_ID),
        "prefix": _js_string(BADGE_PREFIX),
        "profile_name": _js_string((profile or "").strip()),
        "accent": _js_string(badge_accent(profile)),
        "idle": _js_string(IDLE_COLOUR),
        "account": _js_string(account or ""),
        "impersonating": _js_string(IMPERSONATING_COLOUR),
        "collapsed_key": _js_string(COLLAPSED_KEY),
        "user_script": _USER_RESOLVER,
        "active_ttl_ms": int(ACTIVE_TTL_S * 1000),
        "keepalive_ms": KEEPALIVE_MS,
    }


def badge_activity_script(active: bool) -> str:
    """Light or clear the activity dot. A no-op if the badge is not mounted."""
    return _ACTIVITY_TEMPLATE % {
        "host_id": _js_string(BADGE_ELEMENT_ID),
        "state": "true" if active else "false",
    }


def hide_badge_script() -> str:
    """Hide the badge so it never lands in a screenshot."""
    return _TOGGLE_TEMPLATE % {"host_id": _js_string(BADGE_ELEMENT_ID), "display": "'none'"}


def show_badge_script() -> str:
    return _TOGGLE_TEMPLATE % {"host_id": _js_string(BADGE_ELEMENT_ID), "display": "''"}


__all__ = [
    "BADGE_ELEMENT_ID",
    "BADGE_PREFIX",
    "COLLAPSED_KEY",
    "IMPERSONATING_COLOUR",
    "KEEPALIVE_MS",
    "badge_accent",
    "badge_init_script",
    "badge_label",
    "hide_badge_script",
    "show_badge_script",
]
