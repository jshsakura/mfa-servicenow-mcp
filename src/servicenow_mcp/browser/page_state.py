"""What the page shows after a batch, as a few hundred characters of text.

A batch used to return only "step ok" and the URL, so the caller could not tell
what its click had opened without a screenshot. In one Workflow Studio session
108 of 117 act calls attached a viewport image for exactly that: an image per
step is the most expensive way to read "the dropdown now lists Closed, Open".

This reads the same answer from the DOM: the focused field, the open listbox or
menu, any dialog, any alert. Shadow roots are walked because Next Experience
pages (Workflow Studio among them) keep their controls inside them, where a
plain querySelectorAll sees nothing.

Bounded on purpose: node count, items per list, characters per item. A state
that was cut says so (``truncated``) rather than reading as the whole page.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Runs in the page. Returns only short strings; never throws.
PAGE_STATE_SCRIPT = r"""
() => {
  const MAX_NODES = 25000, MAX_ITEMS = 15, MAX_CHARS = 60;
  let seen = 0, truncated = false;
  const clip = s => (s || '').replace(/\s+/g, ' ').trim().slice(0, MAX_CHARS);
  const visible = el => {
    if (!el.getClientRects().length) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  };
  const label = el => clip(
    el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
    el.getAttribute('title') || el.getAttribute('name') || el.innerText || ''
  );
  const roles = {option: [], menuitem: [], dialog: [], alert: [], tab: []};
  const walk = root => {
    const it = root.querySelectorAll('*');
    for (const el of it) {
      if (++seen > MAX_NODES) { truncated = true; return; }
      if (el.shadowRoot) walk(el.shadowRoot);
      const role = el.getAttribute && el.getAttribute('role');
      let key = null;
      if (role === 'option' || role === 'menuitem' || role === 'tab') key = role;
      else if (role === 'dialog' || role === 'alertdialog') key = 'dialog';
      else if (role === 'alert' || role === 'status') key = 'alert';
      if (!key || roles[key].length >= MAX_ITEMS || !visible(el)) continue;
      let text;
      if (key === 'dialog') {
        // A nested role=dialog (React modal content + its wrapper) is one dialog.
        if (el.parentElement && el.parentElement.closest('[role=dialog],[role=alertdialog]')) continue;
        const ref = el.getAttribute('aria-labelledby');
        const byId = ref && el.ownerDocument.getElementById(ref.split(' ')[0]);
        const h = el.querySelector('h1,h2,h3,h4,h5,[role=heading]');
        const title = clip(el.getAttribute('aria-label') || (byId && byId.innerText) ||
                           (h && h.innerText) || el.innerText);
        // Its buttons are the next move — the reason a dialog is worth reporting.
        const buttons = [...el.querySelectorAll('button,[role=button]')].filter(visible)
          .map(b => clip(b.innerText || b.getAttribute('aria-label'))).filter(Boolean);
        text = buttons.length ? `${title} [${[...new Set(buttons)].slice(0, 6).join(' | ')}]` : title;
      } else {
        text = clip(el.innerText || el.getAttribute('aria-label') || '');
      }
      if (!text) continue;
      if (key === 'tab' && el.getAttribute('aria-selected') !== 'true') continue;
      if (key === 'option' && el.getAttribute('aria-selected') === 'true') text += ' (selected)';
      if (!roles[key].includes(text)) roles[key].push(text);
    }
  };
  try { walk(document); } catch (e) { truncated = true; }
  let a = document.activeElement;
  while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
  const out = {};
  if (a && a !== document.body) {
    out.focused = {tag: a.tagName.toLowerCase(), label: label(a)};
    if ('value' in a && typeof a.value === 'string' && a.value) out.focused.value = clip(a.value);
    const exp = a.getAttribute('aria-expanded');
    if (exp) out.focused.expanded = exp === 'true';
    // A menu that took focus often has no ARIA roles (plain <a> items), so the
    // role scan above misses it. Its items are the focused element's siblings:
    // the nearest ancestor holding several clickables lists them.
    const CLICKABLE = 'a,button,[role=option],[role=menuitem],li,[tabindex="0"]';
    let up = a.parentElement || (a.getRootNode && a.getRootNode().host);
    for (let i = 0; up && i < 6; i++) {
      const items = [...up.querySelectorAll(CLICKABLE)].filter(visible);
      if (items.length > 60) break;  // climbed out of the menu into the page
      const names = [];
      for (const it of items) {
        const t = clip(it.innerText) || label(it);
        if (t && !names.includes(t)) names.push(t);
        if (names.length >= MAX_ITEMS) break;
      }
      if (names.length >= 3) { out.near_focus = names; break; }
      up = up.parentElement || (up.getRootNode && up.getRootNode().host);
    }
  }
  if (roles.option.length) out.options = roles.option;
  if (roles.menuitem.length) out.menu = roles.menuitem;
  if (roles.dialog.length) out.dialogs = roles.dialog;
  if (roles.alert.length) out.alerts = roles.alert;
  if (roles.tab.length) out.selected_tabs = roles.tab;
  if (truncated) out.truncated = true;
  return out;
}
"""


def read_page_state(page: Any) -> Dict[str, Any]:
    """The page's visible interactive state as text, or ``{"unread": reason}``.

    Never raises. An unread state says so, never comes back as ``{}`` — an
    empty dict means the page was read and has no focus, list, dialog or alert.
    """
    try:
        frames = list(page.frames)
    except Exception:  # noqa: BLE001
        frames = [page]
    merged: Dict[str, Any] = {}
    read_any = False
    last_error = ""
    # Classic forms live in the gsft_main frame; the focused element there shows
    # up in the top document as just "iframe", so a frame's own focus wins.
    for frame in frames[:6]:
        try:
            state = frame.evaluate(PAGE_STATE_SCRIPT)
        except Exception as exc:  # noqa: BLE001 - a detached or navigating frame
            last_error = str(exc)[:120]
            continue
        if not isinstance(state, dict):
            continue
        read_any = True
        focused = state.pop("focused", None)
        if focused and (focused.get("tag") != "iframe" or "focused" not in merged):
            merged["focused"] = focused
        for key, value in state.items():
            if isinstance(value, list):
                merged.setdefault(key, [])
                merged[key] += [v for v in value if v not in merged[key]]
            else:
                merged[key] = value
    if not read_any:
        logger.debug("Could not read the page state: %s", last_error)
        return {"unread": last_error or "no readable frame"}
    return merged
