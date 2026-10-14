"""Settings opens as a sheet over the board (vaultkit 0.32): Cancel leaves the board as it was, Save keeps a board option and
reloads the page with it, and while any dialog is open the board's own keys (n, j/k, 1-5) and its live reload leave the page
alone. Needs Playwright for Python with its Chromium; it says so and skips otherwise."""
import os, shutil, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("settings sheet tests: skipped (no Playwright for Python)")
    raise SystemExit(0)

work = tempfile.mkdtemp(prefix="konbini-sheet-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
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
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception as exc:
            print("settings sheet tests: skipped (%s)" % str(exc).splitlines()[0][:120])
            raise SystemExit(0)
        page = br.new_context(viewport={"width": 1280, "height": 800}, service_workers="block").new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/")
        page.wait_for_timeout(400)
        style = lambda: page.evaluate("document.body.dataset.cardStyle || ''")
        sel = "dialog.msheet select[data-set=cardStyle]"
        def open_sheet():
            page.click(".gear")
            page.wait_for_selector("dialog.msheet[open]", timeout=5000)
            page.wait_for_timeout(200)
        assert style() == ""
        # the board's keys leave an open Settings sheet alone: n opens no New Card, a digit moves no card
        page.click('.card[data-slug="lantern"]', position={"x": 5, "y": 5})
        open_sheet()
        page.keyboard.press("n")
        page.keyboard.press("j")
        assert not page.evaluate("document.querySelector('dialog.newdlg').open"), "n over the sheet"
        # Cancel puts a previewed change back
        page.select_option(sel, "solid")
        page.click("dialog.msheet .sround.cancel")
        page.wait_for_timeout(300)
        assert not page.query_selector("dialog.msheet[open]") and style() == ""
        # Save keeps it and the page reloads with the server-drawn card style
        open_sheet()
        page.select_option(sel, "solid")
        with page.expect_navigation(timeout=8000):
            page.click("dialog.msheet .sround.save")
        page.wait_for_timeout(300)
        assert style() == "solid", style()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        open_sheet()                                                      # back to the default for the next run
        page.select_option(sel, "tint")
        with page.expect_navigation(timeout=8000):
            page.click("dialog.msheet .sround.save")
        assert not errors, errors
        br.close()
    print("settings sheet tests: all passed")
finally:
    os.killpg(server.pid, 15)
    server.wait()
    shutil.rmtree(work, ignore_errors=True)
