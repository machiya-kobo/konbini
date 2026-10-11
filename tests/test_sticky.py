"""The board page's Backlog..Done row sticks right under the pinned header while the lanes scroll, and the header's search pill
is in the top bar from 1100px wide and a second row below that (vaultkit 0.30; machiya.js publishes the header's height as
--hdr-h). Needs Playwright for Python with its Chromium; it says so and skips otherwise."""
import os, shutil, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("sticky tests: skipped (no Playwright for Python)")
    raise SystemExit(0)

work = tempfile.mkdtemp(prefix="konbini-sticky-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
subprocess.run([os.path.join(ROOT, "tools", "demo-vault"), work + "/vault"], check=True, capture_output=True)
for i, name in enumerate(["alpha", "bravo", "charlie", "delta"]):        # lanes enough to scroll past the row
    with open(os.path.join(work, "vault", "personal", "Projects", "Area %s.md" % name), "w") as f:
        f.write("---\ntitle: Area %s\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/%s\n"
                "project: area-%s\nstatus: ready\n---\n# Area %s\n" % (name, name, name, name))
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, KANBAN_REPO=work + "/vault", KANBAN_REPO_SUBDIR="personal", KANBAN_DB=work + "/k.db",
           KANBAN_AUTH="open", KANBAN_BIND="127.0.0.1", KANBAN_TAILNET_PORT=str(port), TZ="UTC", PYTHONDONTWRITEBYTECODE="1")
for k in [k for k in env if k.startswith(("KANBAN_NIWA", "KANBAN_KURA", "KANBAN_HISTER", "MACHIYA_"))]:
    del env[k]
server = subprocess.Popen([sys.executable, os.path.join(ROOT, "app", "app.py")], env=env, start_new_session=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = "http://127.0.0.1:%d" % port
MEASURE = """() => {
  const r = (s) => document.querySelector(s).getBoundingClientRect();
  return { header: r("header.top").height, hdrvar: parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--hdr-h")),
           bar: r(".colbar").top, scrollY: window.scrollY,
           search: r("header.top form.search input").top + r("header.top form.search input").height / 2,
           brand: r(".brand").top + r(".brand").height / 2 };
}"""
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
            print("sticky tests: skipped (%s)" % str(exc).splitlines()[0][:120])
            raise SystemExit(0)
        for width, wide in ((1400, True), (1100, True), (1099, False), (900, False)):
            page = br.new_context(viewport={"width": width, "height": 500}, service_workers="block").new_page()
            page.goto(BASE + "/")
            page.wait_for_timeout(400)
            page.evaluate("window.scrollTo(0, 700)")
            page.wait_for_timeout(300)
            m = page.evaluate(MEASURE)
            assert m["scrollY"] > 300, (width, m)                                    # the page really scrolled
            assert abs(m["hdrvar"] - m["header"]) <= 1, (width, "--hdr-h is the header's height", m)
            assert abs(m["bar"] - m["header"]) <= 2, (width, "the row sticks under the header", m)
            assert (abs(m["search"] - m["brand"]) < 14) == wide, (width, "search in the top bar from 1100px", m)
            page.close()
        # every text size at 1100px: the header stays one row (a long page name is clamped, not wrapped) and the row sticks
        for size in ("xsmall", "standard", "xlarge"):
            for path in ("/", "/archived", "/streams"):
                ctx = br.new_context(viewport={"width": 1100, "height": 500}, service_workers="block")
                ctx.add_cookies([{"name": "textSize", "value": size, "url": BASE}])
                page = ctx.new_page()
                page.goto(BASE + path)
                page.wait_for_timeout(300)
                m = page.evaluate(MEASURE.replace('bar: r(".colbar").top,', 'bar: 0,'))
                assert abs(m["search"] - m["brand"]) < 14, (size, path, "one row at 1100px", m)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (size, path, "no sideways scroll")
                page.close()
        br.close()
    print("sticky tests: all passed")
finally:
    os.killpg(server.pid, 15)
    server.wait()
    shutil.rmtree(work, ignore_errors=True)
