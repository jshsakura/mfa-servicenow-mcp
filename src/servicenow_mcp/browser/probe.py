"""The in-page collector: the window records its own activity; we harvest it.

Why the page collects instead of the tool listening
---------------------------------------------------
Each tool call attaches over CDP, reads, and detaches. A listener-based design
would therefore only ever see events that happen while a tool call is running —
which is exactly when the user is NOT clicking. Everything that matters (the
double-submit, the console error on save) would land in the gap between calls
and be lost.

So a small script is injected on every document. It buffers console output,
uncaught errors, and every XHR/fetch into a capped ring buffer, mirrored to
``sessionStorage`` so it survives navigation within the tab. Harvesting is then
a single evaluate() with no attached wait, which is also what makes
``watch_seconds=0`` meaningful: the history is already there.

The buffer is capped in the page, not in Python. Trimming at the source is what
keeps a runaway error loop (the same error 40,000 times) from ever becoming a
payload we have to receive, parse, and pay for.
"""

import json
from typing import Any

# Ring buffer size. 400 events comfortably covers a form submit plus its
# fallout while staying a few hundred KB at worst.
MAX_EVENTS = 400

# Request/response bodies are summarized, never stored whole: a hash to compare
# calls for equality, plus a short head for a human to recognize it by.
BODY_HEAD_CHARS = 200

PROBE_GLOBAL = "__snMcpProbe"
_STORAGE_KEY = "__sn_mcp_probe_events__"

# Mirroring every event to sessionStorage would re-serialize the whole buffer
# on every XHR. Throttled: a lost tail on a hard navigation is a fair trade.
_MIRROR_INTERVAL_MS = 500

PROBE_SCRIPT = """
(() => {
  const G = '%(global)s';
  if (window[G]) {
    // Same Window, new document — see `rearm` below.
    try { if (window[G].doc !== document && window[G].rearm) window[G].rearm(false); } catch (e) {}
    return;
  }

  const MAX = %(max_events)d;
  const HEAD = %(head)d;
  const KEY = '%(storage_key)s';
  const MIRROR_MS = %(mirror_ms)d;

  let seq = 0;
  let events = [];
  let lastMirror = 0;
  // When a human last touched THIS tab. Mirrored like the events are, because
  // clicking a link is itself an interaction: without carrying it across the
  // navigation, somebody actively browsing would look untouched on every new
  // document, which is exactly backwards.
  let lastHuman = 0;
  // WHOSE seq numbers these are. `seq` counts from 1 in every tab, while the
  // caller's high-water mark used to be one number per WINDOW — so a mark of
  // 120 taken in one tab, applied to a second tab sitting at 40, filtered away
  // every event it had and reported a clean page nobody had read. Lives in
  // sessionStorage, which is per tab and survives navigation, exactly like the
  // buffer whose numbering it identifies.
  let tabId = '';

  // --- frames ----------------------------------------------------------
  // Every caller reads the TOP document's probe. A probe in a child frame used
  // to keep a buffer of its own that nothing ever drained, so a classic form
  // inside `gsft_main` could throw, fail a save and be typed into by a person
  // while the window reported "No errors", no dirty field and nobody there
  // (measured in a real Chromium). A same-origin child therefore hands every
  // record to the top probe (`adopt`) and keeps nothing itself. A child that
  // cannot reach it — cross-origin, or a top probe too old to adopt — is
  // listed by the top's drain() as a frame NOT observed, never as a clean one.
  let isChild = false;
  try { isChild = window.top !== window.self; } catch (e) { isChild = true; }
  let host = null;
  if (isChild) {
    try {
      const h = window.top[G];
      if (h && (h.version || 0) >= 6 && h.adopt) host = h.adopt;
    } catch (e) { host = null; }
  }
  const frameName = (() => {
    if (!isChild) return '';
    try { return String(window.name || location.pathname || 'frame').slice(0, 60); } catch (e) { return 'frame'; }
  })();

  // sessionStorage is per TAB and shared by every same-origin frame in it, so
  // the key is the top document's alone. A child reading it inherited the
  // top's buffer and tabId; a child writing it overwrote the top's mirror.
  if (!isChild) {
    try {
      const saved = sessionStorage.getItem(KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed.events)) { events = parsed.events; seq = parsed.seq || 0; }
        lastHuman = parsed.lastHuman || 0;
        tabId = parsed.tabId || '';
      }
    } catch (e) { /* storage blocked or corrupt — start fresh */ }
  }

  if (!tabId) {
    tabId = 't' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  const mirror = (force) => {
    if (isChild) return;
    const now = Date.now();
    if (!force && now - lastMirror < MIRROR_MS) return;
    lastMirror = now;
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ events, seq, lastHuman, tabId }));
    } catch (e) {}
  };
  mirror(true);

  // Cheap, stable string hash (FNV-1a). Only used to decide "same payload?",
  // never for anything security-bearing.
  const hash = (s) => {
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h.toString(16);
  };

  // Credentials are stripped HERE, in the page, before anything is buffered.
  // The window signs itself in (auto-login fills a real password into a real
  // form), and an IdP that posts that form over fetch would otherwise leave the
  // password in `head` — which is written to an artifacts file on disk. Doing
  // it at the source means no later stage has to remember to.
  const SECRET_KEY = /(password|passwd|pwd|secret|token|api[_-]?key|authorization|sessionid)/i;
  const redact = (s) => s.replace(
    /([?&;]?[\\w.\\-\\[\\]]*(?:password|passwd|pwd|secret|token|api[_-]?key|authorization|sessionid)[\\w.\\-\\[\\]]*"?\\s*[:=]\\s*"?)([^"&;,}\\s]*)/gi,
    '$1<redacted>'
  );

  const summarize = (body) => {
    if (body == null) return null;
    let text;
    try {
      if (typeof body === 'string') text = body;
      else if (body instanceof URLSearchParams) text = body.toString();
      else if (body instanceof FormData) text = [...body.entries()].map(p => p[0] + '=' + (SECRET_KEY.test(p[0]) ? '<redacted>' : p[1])).join('&');
      else text = JSON.stringify(body);
    } catch (e) { return { bytes: -1, hash: null, head: '[unserializable]' }; }
    if (typeof text !== 'string') return null;
    const bytes = text.length;
    text = redact(text);
    // Hashed AFTER redaction: the hash only has to be stable enough to answer
    // "same payload twice?", and two identical submits redact identically.
    return { bytes: bytes, hash: hash(text), head: text.slice(0, HEAD) };
  };

  const record = (event) => {
    events.push(Object.assign({ seq: ++seq, t: Date.now() }, event));
    if (events.length > MAX) events = events.slice(events.length - MAX);
    mirror(false);
  };
  const push = (event) => {
    if (host) {
      try { host.push(event, frameName); return; } catch (e) { host = null; }
    }
    record(event);
  };

  // --- console ---------------------------------------------------------
  ['error', 'warn'].forEach((level) => {
    const original = console[level];
    console[level] = function () {
      try {
        const msg = Array.from(arguments).map((a) => {
          if (a instanceof Error) return a.message;
          if (typeof a === 'object') { try { return JSON.stringify(a); } catch (e) { return String(a); } }
          return String(a);
        }).join(' ');
        push({ kind: 'console', level, msg: msg.slice(0, 600) });
      } catch (e) {}
      return original.apply(console, arguments);
    };
  });

  // --- uncaught errors -------------------------------------------------
  window.addEventListener('error', (e) => {
    push({
      kind: 'error', level: 'error',
      msg: String((e && e.message) || 'script error').slice(0, 600),
      source: String((e && e.filename) || ''),
      line: (e && e.lineno) || 0,
      stack: String((e && e.error && e.error.stack) || '').slice(0, 1200)
    });
  }, true);

  window.addEventListener('unhandledrejection', (e) => {
    const reason = e && e.reason;
    push({
      kind: 'error', level: 'error',
      msg: ('unhandled rejection: ' + String((reason && reason.message) || reason)).slice(0, 600),
      stack: String((reason && reason.stack) || '').slice(0, 1200)
    });
  });

  // Requests still open, by start time: what "has the page finished reacting to
  // that keypress" waits on. Only recent ones count (busy()), so a long poll
  // opened minutes ago does not hold every step to its cap.
  const openReqs = new Map();
  let openSeq = 0;
  const openLocal = () => { const id = ++openSeq; openReqs.set(id, Date.now()); return id; };
  // A child's request holds the TOP's busy() open: a save inside gsft_main is
  // exactly what a click's settle has to wait for.
  const opened = () => {
    if (host) { try { return host.opened(); } catch (e) { host = null; } }
    return openLocal();
  };
  const closed = (id) => {
    if (host) { try { host.closed(id); return; } catch (e) { host = null; } }
    openReqs.delete(id);
  };

  // --- XMLHttpRequest --------------------------------------------------
  const OpenOriginal = XMLHttpRequest.prototype.open;
  const SendOriginal = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__snMcp = { method: String(method || 'GET').toUpperCase(), url: String(url || '') };
    return OpenOriginal.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    const meta = this.__snMcp || {};
    const started = Date.now();
    const openId = opened();
    this.addEventListener('loadend', () => {
      closed(openId);
      push({
        kind: 'xhr', transport: 'xhr',
        method: meta.method || 'GET', url: redact(meta.url || ''),
        status: this.status, ms: Date.now() - started,
        req: summarize(body),
        resBytes: (this.responseText || '').length
      });
    });
    return SendOriginal.apply(this, arguments);
  };

  // --- fetch -----------------------------------------------------------
  if (window.fetch) {
    const fetchOriginal = window.fetch;
    window.fetch = function (input, init) {
      const started = Date.now();
      const url = redact(String((input && input.url) || input || ''));
      const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
      const body = init && init.body;
      const openId = opened();
      return fetchOriginal.apply(this, arguments).then((response) => {
        closed(openId);
        push({
          kind: 'xhr', transport: 'fetch', method, url,
          status: response.status, ms: Date.now() - started, req: summarize(body), resBytes: -1
        });
        return response;
      }, (err) => {
        closed(openId);
        push({
          kind: 'xhr', transport: 'fetch', method, url,
          status: 0, ms: Date.now() - started, req: summarize(body),
          resBytes: -1, error: String((err && err.message) || err).slice(0, 300)
        });
        throw err;
      });
    };
  }

  // --- what the page SAYS went wrong ----------------------------------
  // A save the client refused, a mandatory field, a Business Rule's
  // gs.addErrorMessage: none of these is a console error or a failed request,
  // so a read that only counted those printed "No errors" under a red banner.
  // Measured on a real instance: the classic banner is
  // `div.outputmsg_error.notification-error[role=alert]`; the Service Portal
  // toast is `.notification-container > .alert.alert-danger` and is GONE a few
  // seconds later, so reading the DOM when a batch ends can miss it. Recorded
  // as it appears instead, like every other event.
  const MSG_SELECTOR = '.outputmsg_error, .notification-error, .notification-container .alert-danger';
  const seenMsg = new WeakSet();
  const noteMessage = (el, preexisting) => {
    if (seenMsg.has(el)) return;
    seenMsg.add(el);
    // Angular fills the text a digest after the node lands.
    setTimeout(() => {
      try {
        const text = String(el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
        if (!text) return;
        const ev = { kind: 'ui_message', level: 'error', msg: text.slice(0, 300) };
        if (preexisting) ev.preexisting = true;
        push(ev);
      } catch (e) {}
    }, 60);
  };
  const scanMessages = (root, preexisting) => {
    try {
      if (root.matches && root.matches(MSG_SELECTOR)) noteMessage(root, preexisting);
      if (root.querySelectorAll) for (const el of root.querySelectorAll(MSG_SELECTOR)) {
        // The inner node of an already-noted banner is the same message.
        if (el.parentElement && el.parentElement.closest(MSG_SELECTOR)) continue;
        noteMessage(el, preexisting);
      }
    } catch (e) {}
  };
  const armMessages = (preexisting) => {
    try {
      new MutationObserver((mutations) => {
        for (const m of mutations) {
          if (m.type === 'attributes') { scanMessages(m.target, false); continue; }
          for (const n of m.addedNodes) if (n.nodeType === 1) scanMessages(n, false);
        }
      }).observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
    } catch (e) {}
    // What is on screen now was never seen appearing. On a late injection it is
    // reported and marked preexisting; on a rearm at DOMContentLoaded the whole
    // document was parsed since, so it is this document's own.
    if (document.readyState !== 'loading') scanMessages(document, preexisting);
  };
  armMessages(true);

  // Same Window, NEW document. A frame the Next Experience shell creates and
  // then points at a classic form keeps its Window object while the Document
  // is replaced, and the init script does NOT run again for it. Measured on
  // gsft_main: the probe's document !== the live one, so the observer watched
  // a discarded document — console/XHR hooks (on the Window) kept reporting
  // and the red banner never did. Window listeners survive the swap, and
  // DOMContentLoaded bubbles from the new document to the Window: that is the
  // moment to re-arm. drain() checks again for any frame that slipped past.
  let armedDoc = document;
  const rearm = (preexisting) => {
    if (armedDoc === document) return;
    armedDoc = document;
    armMessages(!!preexisting);
    if (window[G]) window[G].doc = document;
  };
  window.addEventListener('DOMContentLoaded', () => rearm(false), true);

  // --- who actually typed ----------------------------------------------
  // `isTrusted` is the browser's own answer to "did a human do this": events
  // from a real keystroke are trusted, `el.value = x` and dispatchEvent are
  // not. Comparing against defaultValue cannot tell the two apart — on a
  // Service Portal page every ng-model-bound field differs from its (empty)
  // HTML value attribute, so a widget initializing itself looked exactly like
  // a half-filled form.
  const touched = new WeakSet();
  // Whether this script reached the document before it rendered. Injected late
  // (an already-loaded page armed after the fact), anything typed BEFORE now
  // was never observed, so the touched set is not evidence of a clean form.
  const installedLate = document.readyState !== 'loading';
  const fieldName = (el) => el.name || el.id || el.getAttribute('ng-model') || el.tagName.toLowerCase();
  const isField = (el) => !!el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName || '');

  // `lastHuman` answers a second question, for the reaper: was anyone at this
  // window recently? Pointer and key events are listened to purely for that —
  // they record no event and touch no field, they only stamp the clock.
  //
  // isTrusted alone does NOT separate a person from the model here: Playwright
  // drives clicks and typing through the CDP Input domain, which goes through
  // the browser's real input pipeline and arrives trusted, exactly like a hand
  // on the mouse. The separation comes from pairing this with the window's
  // last-attach time instead (see reaper.py): the reaper only looks at windows
  // no tool has attached to for a long time, and during that span the model
  // provably generated no input at all — so a recent stamp in that span can
  // only be a person.
  ['input', 'change', 'pointerdown', 'keydown'].forEach((type) => {
    window.addEventListener(type, (e) => {
      if (!e || !e.isTrusted) return;
      if (host) { try { host.human(); } catch (e2) { host = null; } }
      lastHuman = Date.now();
      mirror(false);
      if ((type === 'input' || type === 'change') && isField(e.target)) touched.add(e.target);
    }, true);
  });

  // Fields a human edited and left non-empty. Capped: the caller needs to
  // know THAT input would be lost, not an inventory of the form.
  const dirtyFields = () => {
    const out = [];
    // A navigated-away child document is detached; its touched set describes
    // a form that no longer exists.
    if (!document.defaultView) return { fields: out, observedFromStart: true };
    for (const el of document.querySelectorAll('input, textarea, select')) {
      if (el.type === 'hidden' || el.disabled || el.readOnly) continue;
      if (!touched.has(el)) continue;
      if (el.type === 'checkbox' || el.type === 'radio') { out.push(fieldName(el)); }
      else if (String(el.value || '').length) { out.push(fieldName(el)); }
      if (out.length >= 10) break;
    }
    return { fields: out, observedFromStart: !installedLate };
  };

  if (host) {
    // Adopted: the top probe now holds this frame's events, requests, presence
    // and dirty fields. The stub only stops a second injection, and tells the
    // top's frame census that this frame IS observed.
    let token = 0;
    try { token = host.addFrame(dirtyFields); } catch (e) { token = 0; }
    window.addEventListener('pagehide', () => { try { host && host.dropFrame(token); } catch (e) {} });
    window[G] = { version: 6, child: true, adopted: true, doc: document, rearm };
    return;
  }

  window.addEventListener('pagehide', () => mirror(true));

  // Frames that handed their records here (see `adopt`), by token.
  const childFrames = new Map();
  let frameSeq = 0;
  const allDirty = () => {
    const own = dirtyFields();
    let fields = own.fields.slice();
    let fromStart = own.observedFromStart;
    for (const [token, fn] of childFrames) {
      let part = null;
      try { part = fn(); } catch (e) { childFrames.delete(token); continue; }
      if (!part) continue;
      fields = fields.concat(Array.from(part.fields || []).map(String));
      fromStart = fromStart && !!part.observedFromStart;
    }
    return { fields: fields.slice(0, 10), observedFromStart: fromStart };
  };

  // Which child frames this probe can vouch for. A frame is observed only when
  // its probe was ADOPTED here; one with no probe, a probe of its own, or a
  // cross-origin document is listed, because its errors are not in `events`
  // and a drain without it must not read as a clean page. An empty
  // about:blank frame runs no document code and is skipped.
  const frameCensus = () => {
    const out = { observed: 0, unobserved: [] };
    const walk = (w, depth) => {
      if (depth > 5) return;
      let n = 0;
      try { n = w.frames.length; } catch (e) { return; }
      for (let i = 0; i < n; i++) {
        let f = null, href = '', p = null, cross = false;
        try { f = w.frames[i]; href = String(f.location.href); p = f[G]; } catch (e) { cross = true; }
        if (cross) {
          out.unobserved.push({ url: '', reason: 'cross_origin' });
          continue;
        }
        if (p && p.adopted) {
          out.observed++;
          // A frame whose document was swapped under its Window (see rearm).
          try { if (p.doc !== f.document && p.rearm) p.rearm(true); } catch (e) {}
        }
        else if (!p && (href === 'about:blank' || href === '')) { /* empty frame */ }
        else out.unobserved.push({ url: redact(href).slice(0, 160), reason: p ? 'own_buffer' : 'no_probe' });
        walk(f, depth + 1);
      }
    };
    walk(window, 0);
    return out;
  };

  window[G] = {
    // Bumped when the SHAPE of a call changes, so a caller can tell what the
    // probe in front of it understands. A window open across an upgrade keeps
    // its old probe until the page reloads (the script returns early when the
    // global exists), so "the code shipped" never means "the page has it".
    // 4: drain() takes a {tabId: seq} map instead of a bare number.
    // 5: busy(ms) — requests still open that started within the last ms.
    // 6: adopt — same-origin child frames report here; drain() carries frames.
    version: 6,
    // The document this probe was armed on; see the guard at the top.
    doc: document,
    rearm,
    // A child frame's door into this buffer. Events are copied through JSON so
    // nothing kept here belongs to a frame's realm once that frame is gone.
    adopt: {
      push: (event, frame) => {
        let copy = {};
        try { copy = JSON.parse(JSON.stringify(event)); } catch (e) { copy = { kind: 'error', level: 'error', msg: '[unserializable frame event]' }; }
        copy.frame = String(frame || 'frame').slice(0, 60);
        record(copy);
      },
      opened: () => openLocal(),
      closed: (id) => { openReqs.delete(id); },
      human: () => { lastHuman = Date.now(); mirror(false); },
      addFrame: (fn) => { const token = ++frameSeq; childFrames.set(token, fn); return token; },
      dropFrame: (token) => { childFrames.delete(token); }
    },
    busy: (ms) => {
      const since = Date.now() - (ms || 2500);
      let n = 0;
      for (const t of openReqs.values()) if (t >= since) n++;
      return n;
    },
    dirty: allDirty,
    // Everything the reaper needs to decide "is this window in use?", in one
    // evaluate. `now` is the PAGE's clock so the caller subtracts two readings
    // from the same clock rather than comparing across processes.
    presence: () => ({
      now: Date.now(),
      lastHuman: lastHuman,
      seq: seq,
      tabId: tabId,
      dirty: allDirty().fields.length
    }),
    // Harvest everything newer than this TAB's high-water mark. `marks` is the
    // caller's whole map of tabId -> seq, and the tab picks its own entry: the
    // caller cannot know which tab it is about to reach until it has reached
    // it, and applying another tab's number here is precisely the bug this
    // replaces. An unknown tab starts from 0 — everything it buffered, which
    // over-fetches rather than reporting a page it never read as clean.
    drain: (marks) => {
      const after = (marks && typeof marks === 'object' && marks[tabId]) || 0;
      return {
        seq: seq,
        tabId: tabId,
        url: location.href,
        title: document.title,
        dropped: Math.max(0, seq - events.length - after),
        events: events.filter((ev) => ev.seq > after),
        frames: frameCensus()
      };
    },
    reset: () => { events = []; seq = 0; mirror(true); }
  };
})();
""" % {
    "global": PROBE_GLOBAL,
    "max_events": MAX_EVENTS,
    "head": BODY_HEAD_CHARS,
    "storage_key": _STORAGE_KEY,
    "mirror_ms": _MIRROR_INTERVAL_MS,
}


def busy_script(recent_ms: int) -> str:
    """Expression: requests still open that started in the last *recent_ms*.

    -1 when the probe is absent or older than version 5 (a window open across
    an upgrade keeps its old probe until reload): no signal, never "idle".
    """
    return (
        f"(() => {{ const p = window['{PROBE_GLOBAL}'];"
        f" return (p && p.busy) ? p.busy({int(recent_ms)}) : -1; }})()"
    )


def dirty_script() -> str:
    """Fields a human actually edited, per the in-page trusted-event record.

    Returns null when the probe is absent, which the caller must treat as "no
    evidence" rather than "nothing is dirty" — see capture._dirty_fields.
    """
    return (
        f"(() => {{ const p = window['{PROBE_GLOBAL}'];"
        f" return (p && p.dirty) ? p.dirty() : null; }})()"
    )


def drain_script(marks: Any) -> str:
    """Expression returning this tab's events newer than ITS high-water mark.

    ``marks`` is the whole ``{tabId: seq}`` map and the tab picks its own entry,
    because which tab this lands on is not knowable until it lands.

    **The probe in the page decides which shape it gets.** A window that was
    open across the upgrade still runs the OLD probe — the script returns early
    when its global exists, so nothing changes until that document reloads —
    and the old ``drain`` treats its argument as a number. Handed a map it
    computed ``seq - events.length - {object}`` = NaN, which came back to Python
    as a float NaN and took the whole call down with it. Measured on a live
    window minutes after shipping v1.24.5: every ``inspect`` on that window
    failed until the page was reloaded, which is worse than the bug being fixed.

    So the version is asked at call time and an older probe is handed ``0``: it
    re-sends its whole buffer, which over-fetches rather than misreports. An
    explicit int from the caller is passed through for the same reason.
    """
    if isinstance(marks, int):
        payload = str(int(marks))
        # An explicit mark is a number in either dialect, so an old probe gets
        # the real one rather than being reset to the start of its buffer.
        legacy = payload
    else:
        payload = json.dumps({str(k): int(v) for k, v in dict(marks or {}).items()})
        legacy = "0"
    return (
        f"(() => {{ const p = window['{PROBE_GLOBAL}']; if (!p || !p.drain) return null;"
        f" return p.drain((p.version || 0) >= 4 ? {payload} : {legacy}); }})()"
    )


def reset_script() -> str:
    return f"(() => {{ const p = window['{PROBE_GLOBAL}']; if (p && p.reset) p.reset(); }})()"


def presence_script() -> str:
    """Is anyone using this window? Null when the probe cannot answer.

    Null has two causes and one meaning. Either no probe is installed, or the
    one installed predates ``presence`` — a window that has been open across an
    upgrade keeps its old probe, because the script returns early when the
    global already exists. Both mean *no evidence*, never *nobody is there*, so
    the reaper must refuse to close on null. See reaper.py.
    """
    return (
        f"(() => {{ const p = window['{PROBE_GLOBAL}'];"
        f" return (p && p.presence) ? p.presence() : null; }})()"
    )


__all__ = [
    "BODY_HEAD_CHARS",
    "MAX_EVENTS",
    "PROBE_GLOBAL",
    "PROBE_SCRIPT",
    "busy_script",
    "dirty_script",
    "drain_script",
    "presence_script",
    "reset_script",
]
