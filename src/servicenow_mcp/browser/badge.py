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

import json
import logging
import os
from typing import Any, Dict
from urllib.parse import urlparse

from ..utils.instances import (
    ACTIVE_INSTANCE_ENV,
    INSTANCE_CONFIG_ENV,
    load_instance_config_env,
    resolve_env_reference,
)

logger = logging.getLogger(__name__)

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
#
# Read from THIS document, and failing that from the frames inside it. The
# second half is load-bearing on Next Experience, measured on a live instance:
# the `/now/nav/ui/...` shell has `g_ck` but no user at all, because the classic
# UI it wraps sits in an iframe **inside a shadow root** and `g_user` lives in
# there. A badge that only read its own document showed a blank user on every
# Next Experience page — on the surface whose whole job is saying who you are.
_USER_RESOLVER = """
  const readFrom = (w) => {
    try { if (w.NOW && w.NOW.user && w.NOW.user.userName) return String(w.NOW.user.userName); } catch (e) {}
    try { if (w.g_user && w.g_user.userName) return String(w.g_user.userName); } catch (e) {}
    try { if (w.NOW && w.NOW.user_name) return String(w.NOW.user_name); } catch (e) {}
    return '';
  };
  // The frame a name came from, so the re-read below costs one property access
  // instead of another walk. Cleared when it stops answering.
  let userSource = null;
  const findSource = () => {
    if (readFrom(window)) { userSource = window; return; }
    const seen = new Set();
    const walk = (root, depth) => {
      if (depth > 6 || !root || !root.querySelectorAll) return false;
      let els;
      try { els = root.querySelectorAll('*'); } catch (e) { return false; }
      for (const el of els) {
        if (seen.has(el)) continue;
        seen.add(el);
        if (el.tagName === 'IFRAME') {
          let w = null;
          try { w = el.contentWindow; } catch (e) { w = null; }
          if (w && readFrom(w)) { userSource = w; return true; }
        }
        if (el.shadowRoot && walk(el.shadowRoot, depth + 1)) return true;
      }
      return false;
    };
    walk(document, 0);
  };
  const resolveUser = () => {
    let name = '';
    try { name = userSource ? readFrom(userSource) : ''; } catch (e) { name = ''; }
    if (name) return name;
    userSource = null;
    findSource();
    try { return userSource ? readFrom(userSource) : ''; } catch (e) { return ''; }
  };
  // The globals land well after DOMContentLoaded on Next Experience and the
  // portal, so a single read at mount would almost always come up empty.
  //
  // Once a name appears the watch SLOWS DOWN rather than stopping. It used to
  // stop, on the reasoning that an impersonation reloads the page and re-runs
  // this whole script on the new document — true on a classic page or the
  // portal, and false on Next Experience, where the shell survives and only the
  // inner frame navigates. There the badge would have kept displaying the
  // account long after the session had become somebody else: precisely the
  // wrong-user confusion this badge exists to prevent.
  //
  // ACCOUNT is the user this window SIGNED IN as. Anyone else on screen is an
  // impersonation — including one done by hand through the avatar menu — so the
  // badge shows both names and colours them, rather than quietly swapping one
  // name for another and letting the ACLs of a different user look like a bug.
  const trackUser = (sep, userEl, paint) => {
    let tries = 0;
    let shown = null;
    const tick = () => {
      const user = resolveUser();
      if (user && user !== shown) {
        shown = user;
        const acting = ACCOUNT && user.toLowerCase() !== ACCOUNT.toLowerCase();
        userEl.textContent = acting ? (ACCOUNT + ' \\u2192 ' + user) : user;
        userEl.style.color = acting ? IMPERSONATING : NORMAL_USER;
        userEl.style.fontWeight = acting ? '700' : '500';
        // paint() decides visibility, so a name arriving while the badge is
        // collapsed does not pop it back open behind the user's decision.
        paint();
      }
      // A document that never names anybody is not a ServiceNow UI; stop
      // looking. One that did keeps being watched, so a switch shows up.
      if (shown) { setTimeout(tick, 2000); return; }
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
  const IDLE = %(idle)s;
  const ACCOUNT = %(account)s;
  const IMPERSONATING = %(impersonating)s;
  const NORMAL_USER = 'rgba(233,233,236,.62)';
  const COLLAPSED_KEY = %(collapsed_key)s;
  const KNOWN_INSTANCES = %(instance_names)s;
  const FALLBACK_NAME = %(fallback_name)s;
  // The colour identifies the WINDOW, so it is fixed when the script is built —
  // every tab in one window wears it. The NAME below identifies the tab's
  // instance and is read per document. Two channels, two questions: "same
  // window I was looking at?" and "which instance is this tab on?". Deriving
  // both from the instance name would collapse them into one.
  const ACCENT = %(accent)s;
  if (window[HOST_ID]) return;

  // WHICH instance this is gets read from the DOCUMENT, not baked in from
  // Python, for the same reason the signed-in user is (see above): a value
  // fixed when the script was built is right for at most one tab. It used to
  // be the process-wide SERVICENOW_ACTIVE_INSTANCE, so a window opened on
  // another instance carried the ACTIVE instance's name — a prod window that
  // said 'dev'. That is the precise mistake the badge exists to prevent.
  //
  // An unrecognised host says NOTHING rather than falling back to a name it
  // did not establish: a wrong label here is worse than no label, because the
  // badge is what the wrong-instance question gets answered by.
  const pageHost = (() => {
    try { return String(location.hostname || '').toLowerCase(); } catch (e) { return ''; }
  })();
  const knows = (host) =>
    !!host && Object.prototype.hasOwnProperty.call(KNOWN_INSTANCES, host);
  const PROFILE_NAME = knows(pageHost)
    ? String(KNOWN_INSTANCES[pageHost])
    : (Object.keys(KNOWN_INSTANCES).length ? '' : FALLBACK_NAME);

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


def instance_labels(raw: str | None = None) -> Dict[str, str]:
    """host -> alias, for every configured instance.

    Read from the environment rather than passed in, for the same reason
    :func:`profile_label` reads it: the badge is built deep inside the capture
    path, where no instance registry is in scope. Threading one through every
    frame of that path to label a pill is not worth it.

    Malformed config degrades to an empty map instead of raising. An empty map
    makes the badge fall back to the label it was given; it never invents one.
    """
    source = raw if raw is not None else os.environ.get(INSTANCE_CONFIG_ENV)
    if not source or not str(source).strip():
        return {}
    try:
        entries = load_instance_config_env(str(source))
    except (ValueError, TypeError) as exc:  # noqa: BLE001 - a label never raises
        logger.debug("Cannot read instance aliases for the badge: %s", exc)
        return {}
    labels: Dict[str, str] = {}
    for alias, entry in entries.items():
        raw_url = entry.get("url") or entry.get("instance_url") or ""
        url = (resolve_env_reference(str(raw_url)) or str(raw_url)).strip()
        # A schemeless entry parses as a path, not a netloc, and would drop the
        # instance from the map — leaving a correctly configured tab unlabelled.
        # The rest of the registry tolerates one (see instances.safe_instance_url).
        if url and "://" not in url:
            url = f"//{url}"
        try:
            host = (urlparse(url).hostname or "").lower()
        except (TypeError, ValueError):
            continue
        if host:
            labels[host] = alias
    return labels


def profile_label(config: Any = None) -> str:
    """The label a tab falls back to when its own host is not a known instance.

    NOT the answer to "which instance is this tab on" — that is resolved in the
    page from ``location.hostname`` (see :func:`badge_init_script`), because one
    window can hold tabs on more than one instance and a value baked in here is
    right for at most one of them.

    This used to read ONLY the process-wide ``SERVICENOW_ACTIVE_INSTANCE``,
    while accepting a ``config`` it never looked at. A call routed to another
    instance therefore opened a window there and labelled it with the ACTIVE
    instance's name: a prod window drew 'dev'. The config it is called with now
    wins, and the alias comes from the same registry the routing uses.

    In single-instance mode there is no alias, so the account carries the
    identity on its own and this stays 'default' — matching what the server
    reports.
    """
    try:
        host = (urlparse(str(getattr(config, "instance_url", "") or "")).hostname or "").lower()
    except (TypeError, ValueError):
        host = ""
    if host:
        alias = instance_labels().get(host)
        if alias:
            return alias
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
    """A colour derived from whatever string identifies the WINDOW.

    Colour is an IDENTITY channel here, not a severity one: it answers "is this
    the same window I was looking at a minute ago?" at a glance, across however
    many are open. It deliberately carries no meaning of its own — the meaning
    is in the label right next to it, which spells the instance out in words.

    What is hashed is the window, NOT the name on the badge. Hashing the name
    would make the two halves of the badge answer the same question twice and
    leave "which window" unanswered — two windows on one instance would be
    indistinguishable, which is precisely the case the colour exists for.

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


def badge_init_script(profile: str, account: str = "", window_id: str = "") -> str:
    """The badge for this window.

    ``profile`` is only the FALLBACK label — the instance a tab is actually on
    is resolved in the page from its own hostname, so a window holding tabs on
    two instances labels each one correctly. See :func:`profile_label`.

    ``window_id`` is what the COLOUR is drawn from — anything stable and unique
    per window (the caller passes the Chromium profile directory, since one
    directory is one window). Falls back to ``profile`` when the caller has no
    window to point at, which is only ever a bare script build in a test.

    ``account`` is the user the window signed in as, when the server knows it.
    Anyone else showing up in the page is an impersonation and is drawn as
    ``account → impersonated`` in amber. Left empty (an OAuth or API-key profile
    has no browser username to compare against) the badge just names whoever is
    signed in, as before.
    """
    return _BADGE_TEMPLATE % {
        "host_id": _js_string(BADGE_ELEMENT_ID),
        "prefix": _js_string(BADGE_PREFIX),
        "fallback_name": _js_string((profile or "").strip()),
        "instance_names": json.dumps(instance_labels(), sort_keys=True),
        "accent": _js_string(badge_accent(window_id or profile)),
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
