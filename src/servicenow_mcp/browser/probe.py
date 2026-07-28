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
  if (window[G]) return;

  const MAX = %(max_events)d;
  const HEAD = %(head)d;
  const KEY = '%(storage_key)s';
  const MIRROR_MS = %(mirror_ms)d;

  let seq = 0;
  let events = [];
  let lastMirror = 0;

  try {
    const saved = sessionStorage.getItem(KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed.events)) { events = parsed.events; seq = parsed.seq || 0; }
    }
  } catch (e) { /* storage blocked or corrupt — start fresh */ }

  const mirror = (force) => {
    const now = Date.now();
    if (!force && now - lastMirror < MIRROR_MS) return;
    lastMirror = now;
    try { sessionStorage.setItem(KEY, JSON.stringify({ events, seq })); } catch (e) {}
  };

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

  const push = (event) => {
    events.push(Object.assign({ seq: ++seq, t: Date.now() }, event));
    if (events.length > MAX) events = events.slice(events.length - MAX);
    mirror(false);
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
    this.addEventListener('loadend', () => {
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
      return fetchOriginal.apply(this, arguments).then((response) => {
        push({
          kind: 'xhr', transport: 'fetch', method, url,
          status: response.status, ms: Date.now() - started, req: summarize(body), resBytes: -1
        });
        return response;
      }, (err) => {
        push({
          kind: 'xhr', transport: 'fetch', method, url,
          status: 0, ms: Date.now() - started, req: summarize(body),
          resBytes: -1, error: String((err && err.message) || err).slice(0, 300)
        });
        throw err;
      });
    };
  }

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

  ['input', 'change'].forEach((type) => {
    window.addEventListener(type, (e) => {
      if (!e || !e.isTrusted) return;
      if (isField(e.target)) touched.add(e.target);
    }, true);
  });

  window.addEventListener('pagehide', () => mirror(true));

  window[G] = {
    version: 2,
    // Fields a human edited and left non-empty. Capped: the caller needs to
    // know THAT input would be lost, not an inventory of the form.
    dirty: () => {
      const out = [];
      for (const el of document.querySelectorAll('input, textarea, select')) {
        if (el.type === 'hidden' || el.disabled || el.readOnly) continue;
        if (!touched.has(el)) continue;
        if (el.type === 'checkbox' || el.type === 'radio') { out.push(fieldName(el)); }
        else if (String(el.value || '').length) { out.push(fieldName(el)); }
        if (out.length >= 10) break;
      }
      return { fields: out, observedFromStart: !installedLate };
    },
    // Harvest everything newer than `afterSeq`. The caller keeps the high-water
    // mark, so a repeat call costs only what actually changed.
    drain: (afterSeq) => ({
      seq: seq,
      url: location.href,
      title: document.title,
      dropped: Math.max(0, seq - events.length - (afterSeq || 0)),
      events: events.filter((ev) => ev.seq > (afterSeq || 0))
    }),
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


def dirty_script() -> str:
    """Fields a human actually edited, per the in-page trusted-event record.

    Returns null when the probe is absent, which the caller must treat as "no
    evidence" rather than "nothing is dirty" — see capture._dirty_fields.
    """
    return (
        f"(() => {{ const p = window['{PROBE_GLOBAL}'];"
        f" return (p && p.dirty) ? p.dirty() : null; }})()"
    )


def drain_script(after_seq: int) -> str:
    """Expression that returns every buffered event newer than ``after_seq``."""
    return (
        f"(() => {{ const p = window['{PROBE_GLOBAL}'];"
        f" return p ? p.drain({int(after_seq)}) : null; }})()"
    )


def reset_script() -> str:
    return f"(() => {{ const p = window['{PROBE_GLOBAL}']; if (p) p.reset(); }})()"


__all__ = [
    "BODY_HEAD_CHARS",
    "MAX_EVENTS",
    "PROBE_GLOBAL",
    "PROBE_SCRIPT",
    "dirty_script",
    "drain_script",
    "reset_script",
]
