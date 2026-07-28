"""Run JavaScript in the shared window and bring back something printable.

Two doors, because two very different things get called "run some JS".

**An expression** (``inspect_debug_window(evaluate=...)``) answers a question:
what is ``$scope.data.items.length``, what does ``g_form.getValue('state')``
say, is that element's ``offsetHeight`` zero. It is compiled with
``new Function('return (' + src + ')')``, so a statement body is a SyntaxError
rather than a silent success — you cannot slip a script past the read door by
accident.

**A body** (the ``eval`` action) is a script: statements, awaits, loops. It can
do anything the signed-in user can do, which is why it lives behind the
write-classified tool AND a second explicit approval.

What this is NOT
----------------
A sandbox. An expression can still call a function that writes — ``fetch(...)``
is an expression. The distinction above is about intent and blast radius, not
containment; the containment that actually exists is elsewhere: the window holds
its own ServiceNow session (session.py), the read door is refused on a read-only
instance, and the write door needs two confirmations. Anyone reading this later:
do not add a regex that "blocks mutations". It would block nothing and promise
everything.

Bringing the value back
-----------------------
Whatever comes out is described, not serialized. ``JSON.stringify`` on a live
page throws on cycles, silently drops functions and ``undefined``, and happily
returns four megabytes for a DOM node. So values are walked with a depth cap, a
breadth cap and a total-size cap, and the shapes a browser actually produces —
elements, errors, functions, cycles — are turned into short labels a human
recognizes.
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Imports nothing from capture.py or actions.py on purpose: both of them call
# INTO this module, and a module that evaluates a string has no business
# knowing how a window is attached to.

# A described value is a diagnostic, not a data feed. Anything that needs more
# room than this is a sign the wrong question is being asked — narrow the
# expression rather than raising the cap.
MAX_RESULT_CHARS = 4_000
MAX_STRING_CHARS = 600
MAX_ENTRIES = 50
MAX_DEPTH = 4

# Injected fresh with every call rather than kept as page state: this has to
# work on a document the probe never reached (a login page, an iframe, a page
# loaded before the window was armed).
_DESCRIBE_JS = """
const __describe = (root) => {
  const MAX_STRING = %(max_string)d;
  const MAX_ENTRIES = %(max_entries)d;
  const MAX_DEPTH = %(max_depth)d;
  const seen = new WeakSet();

  const clip = (s) => (s.length > MAX_STRING ? s.slice(0, MAX_STRING) + '…[+' + (s.length - MAX_STRING) + ' chars]' : s);

  const walk = (value, depth) => {
    if (value === null) return null;
    const t = typeof value;
    if (t === 'undefined') return '[undefined]';
    if (t === 'number') return Number.isFinite(value) ? value : String(value);
    if (t === 'boolean') return value;
    if (t === 'bigint') return String(value) + 'n';
    if (t === 'symbol') return String(value);
    if (t === 'string') return clip(value);
    if (t === 'function') return '[function ' + (value.name || 'anonymous') + ']';

    if (value instanceof Error) return '[' + value.name + ': ' + clip(String(value.message)) + ']';
    if (typeof Element !== 'undefined' && value instanceof Element) {
      const id = value.id ? '#' + value.id : '';
      const cls = String(value.className || '').trim().split(/\\s+/).filter(Boolean).slice(0, 3);
      return '[<' + value.tagName.toLowerCase() + id + (cls.length ? '.' + cls.join('.') : '') + '>]';
    }
    if (typeof Node !== 'undefined' && value instanceof Node) return '[' + value.nodeName + ']';
    if (typeof Date !== 'undefined' && value instanceof Date) return value.toISOString();
    if (typeof Promise !== 'undefined' && value instanceof Promise) return '[Promise]';

    if (seen.has(value)) return '[circular]';
    seen.add(value);

    if (depth >= MAX_DEPTH) return Array.isArray(value) ? '[Array(' + value.length + ')]' : '[object]';

    if (Array.isArray(value)) {
      const out = value.slice(0, MAX_ENTRIES).map((v) => walk(v, depth + 1));
      if (value.length > MAX_ENTRIES) out.push('…[+' + (value.length - MAX_ENTRIES) + ' more]');
      return out;
    }

    const out = {};
    let count = 0;
    for (const key of Object.keys(value)) {
      if (count++ >= MAX_ENTRIES) { out['…'] = '[+' + (Object.keys(value).length - MAX_ENTRIES) + ' more keys]'; break; }
      try { out[key] = walk(value[key], depth + 1); }
      catch (e) { out[key] = '[getter threw: ' + String(e && e.message || e) + ']'; }
    }
    return out;
  };

  return walk(root, 0);
};
""" % {
    "max_string": MAX_STRING_CHARS,
    "max_entries": MAX_ENTRIES,
    "max_depth": MAX_DEPTH,
}


def expression_script(source: str) -> str:
    """Evaluate ``source`` as a single expression; a statement body is rejected.

    ``new Function`` does the rejecting, and it does it by parsing — no pattern
    matching, no list of forbidden words, nothing to keep up to date.
    """
    return """
    ((src) => {
      %(describe)s
      let fn;
      try {
        fn = new Function('return (' + src + ')');
      } catch (e) {
        return { ok: false, error: 'Not a single expression: ' + String(e && e.message || e) +
                 ". Statements (assignments in sequence, if/for, declarations) need the eval action on act_in_debug_window." };
      }
      try {
        const value = fn();
        return { ok: true, value: __describe(value), type: (value === null ? 'null' : typeof value) };
      } catch (e) {
        return { ok: false, error: String(e && e.message || e), threw: true };
      }
    })(%(source)s)
    """ % {
        "describe": _DESCRIBE_JS,
        "source": _js_string(source),
    }


def body_script(source: str) -> str:
    """Run ``source`` as a statement body and describe whatever it returns.

    Wrapped in an async function so ``await`` works and a returned promise is
    settled before the value is described — otherwise every fetch-based script
    would come back as '[Promise]'.
    """
    return """
    (async (src) => {
      %(describe)s
      let fn;
      try {
        fn = new Function('return (async () => {' + src + '})()');
      } catch (e) {
        return { ok: false, error: 'Syntax error: ' + String(e && e.message || e) };
      }
      try {
        const value = await fn();
        return { ok: true, value: __describe(value), type: (value === null ? 'null' : typeof value) };
      } catch (e) {
        return { ok: false, error: String(e && e.message || e), threw: true };
      }
    })(%(source)s)
    """ % {
        "describe": _DESCRIBE_JS,
        "source": _js_string(source),
    }


def _js_string(value: str) -> str:
    """A JS string literal for *value*.

    json.dumps produces a valid JS string literal for any Python str, which is
    what keeps the caller's source from being able to break out of the wrapper
    and change the surrounding script.
    """
    literal = json.dumps(value)
    # `</script` cannot appear in an inline script body; irrelevant for CDP
    # evaluate, escaped anyway so the same builder is safe if it is ever used
    # to build a <script> tag.
    return literal.replace("</", "<\\/")


def clamp_result(result: Any) -> Dict[str, Any]:
    """Enforce the size cap in Python, where the real budget lives.

    The page caps depth and breadth, which bounds the shape but not the total —
    fifty keys of six hundred characters is still thirty kilobytes.
    """
    if not isinstance(result, dict):
        return {"ok": False, "error": "The page returned an unexpected shape."}
    if not result.get("ok"):
        return {
            "ok": False,
            "error": str(result.get("error") or "evaluation failed")[:600],
            **({"threw": True} if result.get("threw") else {}),
        }

    value = result.get("value")
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"ok": True, "value": str(value)[:MAX_RESULT_CHARS], "type": result.get("type")}

    if len(encoded) <= MAX_RESULT_CHARS:
        return {"ok": True, "value": value, "type": result.get("type")}
    return {
        "ok": True,
        # Truncation is reported, never silent: a value cut in half that reads
        # as complete is worse than no value.
        "value": encoded[:MAX_RESULT_CHARS],
        "type": result.get("type"),
        "truncated": True,
        "note": (
            f"Result exceeded {MAX_RESULT_CHARS} chars and was cut. Narrow the "
            "expression (index into it, or read .length) rather than asking again."
        ),
    }


def run_in_page(page: Any, *, expression: Optional[str] = None, body: Optional[str] = None) -> Dict:
    """Evaluate on an already-attached page. Used by capture() and by actions."""
    script = expression_script(expression) if expression is not None else body_script(body or "")
    try:
        raw = page.evaluate(script)
    except Exception as exc:  # noqa: BLE001 - a hostile page must not break the call
        return {"ok": False, "error": f"The page refused to evaluate: {str(exc)[:300]}"}
    return clamp_result(raw)


__all__ = [
    "MAX_DEPTH",
    "MAX_ENTRIES",
    "MAX_RESULT_CHARS",
    "MAX_STRING_CHARS",
    "body_script",
    "clamp_result",
    "expression_script",
    "run_in_page",
]
