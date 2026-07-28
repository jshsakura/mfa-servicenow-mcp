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

BADGE_ELEMENT_ID = "__sn_mcp_debug_badge__"

# Re-injected on every navigation via add_init_script, so the label survives
# the user clicking through the portal.
_BADGE_TEMPLATE = """
(() => {
  const HOST_ID = %(host_id)s;
  const LABEL = %(label)s;
  if (window[HOST_ID]) return;

  const mount = () => {
    const root = document.documentElement;
    if (!root) return;
    const host = document.createElement('div');
    host.setAttribute('data-sn-mcp-badge', '1');
    // Closed mode: page scripts cannot reach in, page CSS cannot select in.
    const shadow = host.attachShadow({ mode: 'closed' });
    const badge = document.createElement('div');
    badge.textContent = LABEL;
    badge.style.cssText = [
      'position:fixed', 'right:8px', 'bottom:8px', 'z-index:2147483647',
      'font:11px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace',
      'padding:3px 8px', 'border-radius:10px',
      'background:rgba(17,17,17,.82)', 'color:#f2f2f2',
      'pointer-events:none', 'user-select:none',
      'box-shadow:0 1px 4px rgba(0,0,0,.35)'
    ].join(';');
    shadow.appendChild(badge);
    root.appendChild(host);
    window[HOST_ID] = { host, badge };
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


def badge_label(instance_host: str, profile: str) -> str:
    """Short, scannable identity: what this window is and which instance."""
    suffix = f" · {profile}" if profile and profile != instance_host else ""
    return f"MCP DEBUG · {instance_host}{suffix}"


def badge_init_script(instance_host: str, profile: str) -> str:
    return _BADGE_TEMPLATE % {
        "host_id": _js_string(BADGE_ELEMENT_ID),
        "label": _js_string(badge_label(instance_host, profile)),
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
