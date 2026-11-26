"""The in-page collector must see what happens inside child frames.

Every caller reads the TOP document's probe. Before probe v6 a child frame —
the classic form inside ``gsft_main`` — kept a buffer of its own that nothing
drained, so measured in a real Chromium: a console error, an uncaught error and
a 500 inside the frame, plus a person typing into it, came back as "No errors",
no dirty field and ``lastHuman = 0``. That is the reaper's "nobody is here" and
the navigation guard's "nothing to lose" on a form someone is filling in.

These run the real PROBE_SCRIPT in a real headless Chromium against a routed
fake origin — no instance, no user window. CI does not install a browser, so
they skip there; run locally after touching ``browser/probe.py``.
"""

from typing import Any, Dict, Iterator

import pytest

from servicenow_mcp.browser.capture import _arm_frames
from servicenow_mcp.browser.probe import (
    PROBE_SCRIPT,
    busy_script,
    dirty_script,
    drain_script,
    presence_script,
)
from servicenow_mcp.browser.report import compact

ORIGIN = "https://test.service-now.com"
OTHER_ORIGIN = "https://other.example.com"

FRAME_FORM = """<!doctype html><html><body>
<form action="/after.do" method="get"><input id="f" name="short_description"></form>
<script>
console.error('frame-console-error');
setTimeout(() => { throw new Error('frame-uncaught'); }, 30);
fetch('/api/now/table/incident').catch(() => {});
</script></body></html>"""

AFTER = "<!doctype html><html><body><input id='g' name='other'></body></html>"


def _top(frame_src: str) -> str:
    return (
        "<!doctype html><html><head><title>top</title></head><body>"
        f'<iframe id="gsft_main" name="gsft_main" src="{frame_src}"></iframe>'
        "</body></html>"
    )


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 - no browser installed (CI)
            pytest.skip(f"Chromium not available: {exc}")
        yield launched
        launched.close()


def _context(browser: Any, routes: Dict[str, Any], *, init: bool = True) -> Any:
    context = browser.new_context()

    def handle(route: Any) -> None:
        url = route.request.url
        for needle, answer in routes.items():
            if needle in url:
                if callable(answer):
                    answer(route)
                else:
                    route.fulfill(status=200, content_type="text/html", body=answer)
                return
        route.fulfill(status=404, body="")

    context.route(f"{ORIGIN}/**", handle)
    context.route(f"{OTHER_ORIGIN}/**", handle)
    if init:
        context.add_init_script(PROBE_SCRIPT)
    return context


def _api_500(route: Any) -> None:
    route.fulfill(status=500, content_type="application/json", body="{}")


def test_child_frame_events_dirty_and_presence_reach_the_top(browser: Any, tmp_path: Any) -> None:
    context = _context(
        browser,
        {
            "/frame.do": FRAME_FORM,
            "/api/now/table/": _api_500,
            "/nav_to.do": _top(f"{ORIGIN}/frame.do"),
        },
    )
    page = context.new_page()
    page.goto(f"{ORIGIN}/nav_to.do")
    page.wait_for_timeout(300)
    page.frame_locator("#gsft_main").locator("#f").type("hello")
    page.wait_for_timeout(200)

    drained = page.evaluate(drain_script({}))
    by_kind = {(e["kind"], e.get("msg") or e.get("url")): e for e in drained["events"]}
    assert ("console", "frame-console-error") in by_kind
    assert any(k == "error" and "frame-uncaught" in str(m) for k, m in by_kind)
    xhr = by_kind[("xhr", "/api/now/table/incident")]
    assert xhr["status"] == 500 and xhr["frame"] == "gsft_main"
    assert drained["frames"] == {"observed": 1, "unobserved": []}

    assert page.evaluate(dirty_script())["fields"] == ["short_description"]
    assert page.evaluate(presence_script())["lastHuman"] > 0

    report = compact({**drained, "watched_seconds": 0}, artifacts_dir=str(tmp_path))
    assert "console error" in report["verdict"]
    assert "failed request" in report["verdict"]
    context.close()


def test_a_request_open_in_a_child_frame_keeps_the_top_busy(browser: Any) -> None:
    held = []

    def hold(route: Any) -> None:
        held.append(route)  # never answered while we look

    context = _context(
        browser,
        {
            "/frame.do": "<script>fetch('/api/now/slow').catch(()=>{})</script>",
            "/api/now/slow": hold,
            "/nav_to.do": _top(f"{ORIGIN}/frame.do"),
        },
    )
    page = context.new_page()
    page.goto(f"{ORIGIN}/nav_to.do")
    page.wait_for_timeout(300)
    assert page.evaluate(busy_script(10_000)) == 1
    context.close()


def test_an_already_loaded_frame_is_unobserved_until_armed(browser: Any, tmp_path: Any) -> None:
    context = _context(
        browser,
        {"/frame.do": AFTER, "/nav_to.do": _top(f"{ORIGIN}/frame.do")},
        init=False,
    )
    page = context.new_page()
    page.goto(f"{ORIGIN}/nav_to.do")
    page.wait_for_timeout(200)

    page.evaluate(PROBE_SCRIPT)  # top only, the way a late attach used to arm
    census = page.evaluate(drain_script({}))["frames"]
    assert census["observed"] == 0
    assert [u["reason"] for u in census["unobserved"]] == ["no_probe"]
    report = compact(
        {**page.evaluate(drain_script({})), "watched_seconds": 0}, artifacts_dir=str(tmp_path)
    )
    assert not report["verdict"].startswith("No browser errors")
    assert report["frames_unobserved"][0]["reason"] == "no_probe"

    assert _arm_frames(page) == 1
    page.frame(name="gsft_main").evaluate("console.error('after-arm')")
    drained = page.evaluate(drain_script({}))
    assert drained["frames"]["observed"] == 1
    assert any(e.get("msg") == "after-arm" for e in drained["events"])
    context.close()


def test_a_cross_origin_frame_is_listed_not_assumed_clean(browser: Any) -> None:
    context = _context(
        browser,
        {"/x.html": AFTER, "/nav_to.do": _top(f"{OTHER_ORIGIN}/x.html")},
    )
    page = context.new_page()
    page.goto(f"{ORIGIN}/nav_to.do")
    page.wait_for_timeout(300)
    census = page.evaluate(drain_script({}))["frames"]
    assert census["unobserved"] == [{"url": "", "reason": "cross_origin"}]
    context.close()


def test_a_navigated_child_frame_drops_its_old_dirty_fields(browser: Any) -> None:
    context = _context(
        browser,
        {
            "/frame.do": FRAME_FORM,
            "/after.do": AFTER,
            "/api/now/table/": _api_500,
            "/nav_to.do": _top(f"{ORIGIN}/frame.do"),
        },
    )
    page = context.new_page()
    page.goto(f"{ORIGIN}/nav_to.do")
    page.wait_for_timeout(300)
    frame = page.frame_locator("#gsft_main")
    frame.locator("#f").type("hello")
    assert page.evaluate(dirty_script())["fields"] == ["short_description"]

    frame.locator("#f").press("Enter")  # submits the form: the frame navigates
    page.wait_for_timeout(400)
    assert page.evaluate(dirty_script())["fields"] == []
    assert page.evaluate(drain_script({}))["frames"]["observed"] == 1
    context.close()


def test_a_child_frame_never_overwrites_the_top_mirror(browser: Any) -> None:
    context = _context(
        browser,
        {
            "/frame.do": FRAME_FORM,
            "/api/now/table/": _api_500,
            "/nav_to.do": _top(f"{ORIGIN}/frame.do"),
        },
    )
    page = context.new_page()
    page.goto(f"{ORIGIN}/nav_to.do")
    page.wait_for_timeout(300)
    before = page.evaluate(drain_script({}))

    page.reload()  # top restores from sessionStorage
    page.wait_for_timeout(300)
    after = page.evaluate(drain_script({}))
    assert after["tabId"] == before["tabId"]
    # The pre-reload frame events survived in the TOP's mirror, and the reload
    # added a fresh set — nothing a child wrote replaced the buffer.
    first = [e for e in after["events"] if e.get("msg") == "frame-console-error"]
    assert len(first) == 2
    context.close()


# --- on-page error messages ---------------------------------------------------
# Shapes measured on a real instance: the classic banner (server-rendered on the
# form, role=alert) and the Service Portal toast, which removes itself.

CLASSIC_BANNER = """<!doctype html><html><body>
<div class="outputmsg_container"><div class="outputmsg outputmsg_error notification notification-error"
 role="alert"><span class="notification-icon"></span><span class="outputmsg_text">Invalid insert</span></div></div>
</body></html>"""

PORTAL_TOAST = """<!doctype html><html><body><div class="notification-container"></div>
<script>
setTimeout(() => {
  const c = document.querySelector('.notification-container');
  const d = document.createElement('div');
  d.className = 'alert';
  c.appendChild(d);
  // ng-class lands a digest later, and so does the bound text.
  setTimeout(() => { d.className = 'alert alert-danger'; d.innerHTML = '<span class="sr-only">Error</span> The following fields are incomplete: Justification'; }, 10);
  setTimeout(() => d.remove(), 400);
}, 50);
</script></body></html>"""


def test_a_classic_error_banner_is_an_event_not_a_clean_page(browser: Any, tmp_path: Any) -> None:
    context = _context(browser, {"/incident.do": CLASSIC_BANNER})
    page = context.new_page()
    page.goto(f"{ORIGIN}/incident.do")
    page.wait_for_timeout(200)

    drained = page.evaluate(drain_script({}))
    shown = [e for e in drained["events"] if e["kind"] == "ui_message"]
    assert [e["msg"] for e in shown] == ["Invalid insert"]
    report = compact({**drained, "watched_seconds": 0}, artifacts_dir=str(tmp_path))
    assert report["verdict"].startswith("1 on-page error message(s): Invalid insert")
    context.close()


def test_a_portal_toast_is_recorded_even_after_it_is_gone(browser: Any) -> None:
    context = _context(browser, {"/sp": PORTAL_TOAST})
    page = context.new_page()
    page.goto(f"{ORIGIN}/sp?id=sc_cat_item")
    page.wait_for_timeout(800)  # the toast has removed itself by now

    assert page.evaluate("document.querySelectorAll('.alert').length") == 0
    shown = [e for e in page.evaluate(drain_script({}))["events"] if e["kind"] == "ui_message"]
    assert len(shown) == 1
    assert "fields are incomplete" in shown[0]["msg"]
    context.close()


def test_a_banner_already_on_screen_at_a_late_arm_is_marked_preexisting(browser: Any) -> None:
    context = _context(browser, {"/incident.do": CLASSIC_BANNER}, init=False)
    page = context.new_page()
    page.goto(f"{ORIGIN}/incident.do")
    page.evaluate(PROBE_SCRIPT)
    page.wait_for_timeout(200)

    shown = [e for e in page.evaluate(drain_script({}))["events"] if e["kind"] == "ui_message"]
    assert len(shown) == 1 and shown[0]["preexisting"] is True
    context.close()


def test_a_banner_inside_gsft_main_reaches_the_top(browser: Any) -> None:
    context = _context(
        browser,
        {"/incident.do": CLASSIC_BANNER, "/nav_to.do": _top(f"{ORIGIN}/incident.do")},
    )
    page = context.new_page()
    page.goto(f"{ORIGIN}/nav_to.do")
    page.wait_for_timeout(300)

    shown = [e for e in page.evaluate(drain_script({}))["events"] if e["kind"] == "ui_message"]
    assert len(shown) == 1 and shown[0]["frame"] == "gsft_main"
    context.close()


# The Next Experience shell creates gsft_main and then points it at the form.
# Measured live: the frame keeps its Window while its Document is replaced, the
# init script does not run again, and an observer bound to the first document
# saw nothing. Reproduced here the same way the shell does it.
SHELL_TOP = f"""<!doctype html><html><body><script>
const f = document.createElement('iframe');
f.name = 'gsft_main';
document.body.appendChild(f);
setTimeout(() => {{ f.src = '{ORIGIN}/form.do'; }}, 50);
</script></body></html>"""

FORM_SHOWS_BANNER_LATER = """<!doctype html><html><body><div class="outputmsg_container"></div>
<script>
setTimeout(() => {
  document.querySelector('.outputmsg_container').innerHTML =
    '<div class="outputmsg outputmsg_error notification notification-error" role="alert">Mandatory fields</div>';
}, 100);
</script></body></html>"""


def test_a_banner_in_a_frame_whose_document_was_swapped_is_still_seen(browser: Any) -> None:
    context = _context(browser, {"/form.do": FORM_SHOWS_BANNER_LATER, "/shell": SHELL_TOP})
    page = context.new_page()
    page.goto(f"{ORIGIN}/shell")
    page.wait_for_timeout(700)

    shown = [e for e in page.evaluate(drain_script({}))["events"] if e["kind"] == "ui_message"]
    assert [(e["msg"], e.get("frame")) for e in shown] == [("Mandatory fields", "gsft_main")]
    context.close()
