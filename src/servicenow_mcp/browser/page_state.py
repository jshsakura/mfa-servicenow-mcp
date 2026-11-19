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
    // checkVisibility reads the ANCESTORS too (a closing modal fades its wrapper,
    // not the role=dialog node); aria-hidden/inert is how a modal library hides
    // what sits behind it, and a closed one keeps its node for the next open.
    if (el.checkVisibility && !el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
    if (el.closest && el.closest('[aria-hidden="true"],[inert]')) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  };
  const dialogEls = [], popups = [];
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
      if (key === 'dialog') dialogEls.push(el);
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
  // A menu that is OPEN, as opposed to items that are merely on screen: its
  // trigger says so (aria-haspopup + aria-expanded=true). Workflow Studio opens
  // the next "add" menu by itself after Done, and visible items alone could not
  // tell that apart from a static list.
  const findPopups = root => {
    for (const el of root.querySelectorAll('[aria-expanded="true"][aria-haspopup]')) {
      if (popups.length >= 5) return;
      if (el.getAttribute('aria-haspopup') === 'false' || !visible(el)) continue;
      const name = label(el);
      if (name && !popups.includes(name)) popups.push(name);
    }
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) findPopups(el.shadowRoot);
  };
  try { walk(document); } catch (e) { truncated = true; }
  try { findPopups(document); } catch (e) { /* popups are a hint; the rest stands */ }
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
  // Typing goes where focus is. With a dialog open and focus BEHIND it, the
  // fields near focus are the background panel's — read live as the dialog's,
  // two variables were created as subflow inputs. Say it outright.
  if (dialogEls.length && a && a !== document.body) {
    const inside = d => { let n = a; while (n) { if (d.contains(n)) return true; const r = n.getRootNode && n.getRootNode(); n = r && r.host; } return false; };
    if (!dialogEls.some(inside)) out.focus_outside_dialog = true;
  }
  if (popups.length) out.open_popups = popups;
  if (roles.option.length) out.options = roles.option;
  if (roles.menuitem.length) out.menu = roles.menuitem;
  if (roles.dialog.length) out.dialogs = roles.dialog;
  if (roles.alert.length) out.alerts = roles.alert;
  if (roles.tab.length) out.selected_tabs = roles.tab;
  // Workflow Studio's step list, as text: number, nesting and label. This is
  // the structure a screenshot was being read for after every edit. Only this
  // document's own rows; the frame loop on the Python side covers the editor.
  const rows = document.querySelectorAll('.section-item[data-position-order]');
  if (rows.length) {
    const outline = [];
    for (const r of rows) {
      if (outline.length >= 80) { out.outline_truncated = true; break; }
      const box = r.closest('.actionContainer');
      // componentInstance_<index>_<depth>, depth 1 = top level (measured)
      const depth = (parseInt(((box && box.getAttribute('data-position-depth')) || '').split('_').pop(), 10) || 1) - 1;
      let text = (r.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 70);
      // What the text alone does not say (measured on PDI). A labelled If reads
      // as its label, so the kind comes from the container class (if-type,
      // else-type, end-type, setflowvariables-type...), shown when the text
      // does not already start with it.
      const kind = ((box && box.className) || '').split(/\s+/)
        .filter(c => c.endsWith('-type') && c !== 'action-type' && c !== 'flowlogic-type')
        .map(c => c.slice(0, -5))[0];
      const words = text.replace(/^\d+\s*/, '').replace(/^then\s+/i, '').toLowerCase().replace(/[^a-z]/g, '');
      if (kind && !words.startsWith(kind)) text += ` [${kind}]`;
      // The stage chip sits in the step's stage container; empty ones carry isEmpty.
      const holder = r.closest('.instance-component-stage-container');
      const chip = holder && holder.querySelector('.stage-container');
      if (chip && !chip.classList.contains('isEmpty')) {
        const stage = (chip.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 40);
        if (stage) text += ` [stage ${stage}]`;
      }
      // A collapsed block hides its children: say so, or they read as absent.
      const toggle = r.querySelector('.expand-collapse-container [aria-expanded]');
      if (toggle && toggle.getAttribute('aria-expanded') === 'false') text += ' [collapsed]';
      outline.push('  '.repeat(Math.max(0, depth)) + text);
    }
    out.outline = outline;
  }
  if (truncated) out.truncated = true;
  return out;
}
"""


# page url -> hash of the outline last returned. An 80-row outline costs about
# what a screenshot does, so it is sent when it changed and named otherwise.
_LAST_OUTLINE: Dict[str, int] = {}


def _only_if_changed(page: Any, state: Dict[str, Any]) -> None:
    outline = state.get("outline")
    if not outline:
        return
    try:
        key = str(page.url).split("#", 1)[0]
    except Exception:  # noqa: BLE001
        return
    digest = hash(tuple(outline))
    if _LAST_OUTLINE.get(key) == digest:
        state.pop("outline")
        state["outline_unchanged"] = len(outline)
    _LAST_OUTLINE[key] = digest


def read_page_state(page: Any) -> Dict[str, Any]:
    """The page's visible interactive state as text, or ``{"unread": reason}``.

    Never raises. An unread state says so, never comes back as ``{}`` — an
    empty dict means the page was read and has no focus, list, dialog or alert.
    """
    merged = read_page_state_raw(page)
    if "unread" not in merged:
        _only_if_changed(page, merged)
    return merged


def read_page_state_raw(page: Any) -> Dict[str, Any]:
    """read_page_state without the outline dedup: for polling (expect, settle).

    A poll must not record the outline as "already sent", or the report that
    follows would name it unchanged when the caller never saw it.
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
