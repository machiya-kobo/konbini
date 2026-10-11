"""New Card: a filled button in the header's top bar, right after the last tab, opens a dialog with a title and an area (and a
"More" disclosure); n opens it too; it starts on the board's Area filter, else the area used last; Escape and Cancel close it
without adding a card; Add to Backlog makes the card. Needs Playwright for Python with its Chromium; skips otherwise."""
import json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("newcard tests: skipped (no Playwright for Python)")
    raise SystemExit(0)

work = tempfile.mkdtemp(prefix="konbini-newcard-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
subprocess.run([os.path.join(ROOT, "tools", "demo-vault"), work + "/vault"], check=True, capture_output=True)
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, KANBAN_REPO=work + "/vault", KANBAN_REPO_SUBDIR="personal", KANBAN_DB=work + "/k.db",
           KANBAN_AUTH="open", KANBAN_BIND="127.0.0.1", KANBAN_TAILNET_PORT=str(port), TZ="UTC", PYTHONDONTWRITEBYTECODE="1")
for k in [k for k in env if k.startswith(("KANBAN_NIWA", "KANBAN_KURA", "KANBAN_HISTER", "MACHIYA_"))]:
    del env[k]
server = subprocess.Popen([sys.executable, os.path.join(ROOT, "app", "app.py")], env=env, start_new_session=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = "http://127.0.0.1:%d" % port
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/healthz", timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    def titles():
        return [c["title"] for c in json.load(urllib.request.urlopen(BASE + "/api/cards"))["cards"]]
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception as exc:
            print("newcard tests: skipped (%s)" % str(exc).splitlines()[0][:120])
            raise SystemExit(0)
        page = br.new_context(viewport={"width": 1280, "height": 800}, service_workers="block").new_page()
        page.goto(BASE + "/")
        box = lambda sel: page.evaluate("s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }", sel)
        last_tab = page.evaluate("() => { const r = [...document.querySelectorAll('header.top .nav a')].pop().getBoundingClientRect(); return [r.right, r.y + r.height / 2]; }")
        btn = box(".newbtn")
        assert 0 < btn[0] - last_tab[0] < 40 and abs(btn[1] + btn[3] / 2 - last_tab[1]) < 6, ("right after the last tab", btn, last_tab)
        assert not page.is_visible("dialog.newdlg") and not page.is_visible(".newform input[name=title]"), "the form is not in the page"
        # the button opens it on the title; Escape closes it and adds nothing
        page.click(".newbtn")
        assert page.evaluate("document.activeElement.name") == "title" and page.is_visible("dialog.newdlg")
        page.keyboard.press("Escape")
        assert not page.is_visible("dialog.newdlg")
        # n opens it too (not while typing in a field), Cancel closes it
        page.keyboard.press("n")
        assert page.is_visible("dialog.newdlg")
        page.fill("input[name=title]", "n inside the box")
        assert page.input_value("input[name=title]") == "n inside the box"
        page.click("[data-close]")
        assert not page.is_visible("dialog.newdlg") and "n inside the box" not in titles()
        # the board's Area filter picks the area; the one used last is the next default
        areas = page.evaluate("[...document.querySelectorAll('dialog.newdlg select[name=area] option')].map(o => o.value)")
        assert len(areas) > 1, areas
        page.goto(BASE + "/?area=" + areas[1])
        page.click(".newbtn")
        assert page.input_value("select[name=area]") == areas[1], "starts on the Area filter"
        page.fill("input[name=title]", "Popup card")
        page.select_option("select[name=area]", areas[-1])
        page.click("dialog.newdlg button[type=submit]")
        page.wait_for_url("**/p/*")
        assert "Popup card" in titles()
        page.goto(BASE + "/now")
        page.click(".newbtn")
        assert page.input_value("select[name=area]") == areas[-1], "the area used last"
        page.keyboard.press("Escape")
        # phones: the button is in the top bar, the dialog a sheet over the bottom
        ph = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, service_workers="block").new_page()
        ph.goto(BASE + "/")
        assert ph.is_visible(".newbtn")
        ph.tap(".newbtn")
        d = ph.evaluate("() => { const r = document.querySelector('dialog.newdlg').getBoundingClientRect(); return [r.x, r.bottom, r.width, innerHeight]; }")
        assert abs(d[1] - d[3]) < 2 and d[2] >= 389, ("a bottom sheet", d)
        br.close()
    print("newcard tests: all passed")
finally:
    os.killpg(server.pid, 15)
    server.wait()
    shutil.rmtree(work, ignore_errors=True)
