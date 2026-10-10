"""On a phone a horizontal swipe over the lanes switches the column (Ready -> WIP), but a swipe that starts on a control, such
as the row of column tabs or the Area pills, only scrolls that control: it must not also pick a column. Needs Playwright for
Python with its Chromium; it says so and skips otherwise."""
import os, shutil, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("swipe tests: skipped (no Playwright for Python)")
    raise SystemExit(0)

work = tempfile.mkdtemp(prefix="konbini-swipe-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
subprocess.run([os.path.join(ROOT, "tools", "demo-vault"), work + "/vault"], check=True, capture_output=True)
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, KANBAN_REPO=work + "/vault", KANBAN_REPO_SUBDIR="personal", KANBAN_DB=work + "/k.db",
           KANBAN_AUTH="open", KANBAN_BIND="127.0.0.1", KANBAN_TAILNET_PORT=str(port), TZ="UTC", PYTHONDONTWRITEBYTECODE="1")
for k in [k for k in env if k.startswith(("KANBAN_NIWA", "KANBAN_KURA", "KANBAN_HISTER", "MACHIYA_"))]:
    del env[k]
server = subprocess.Popen([sys.executable, os.path.join(ROOT, "app", "app.py")], env=env, start_new_session=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = "http://127.0.0.1:%d" % port
SWIPE = """([sel, dx]) => {
  const el = document.querySelector(sel), r = el.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 20);
  const touch = (px) => new Touch({ identifier: 1, target: el, clientX: px, clientY: y });
  const fire = (type, list) => el.dispatchEvent(new TouchEvent(type, { bubbles: true, cancelable: true,
    touches: type === "touchend" ? [] : list, targetTouches: type === "touchend" ? [] : list, changedTouches: list }));
  fire("touchstart", [touch(x)]); fire("touchmove", [touch(x + dx / 2)]); fire("touchend", [touch(x + dx)]);
  return document.body.dataset.col;
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
            print("swipe tests: skipped (%s)" % str(exc).splitlines()[0][:120])
            raise SystemExit(0)
        ctx = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, service_workers="block")
        page = ctx.new_page()
        page.goto(BASE + "/")
        page.evaluate("localStorage.clear()")
        page.goto(BASE + "/?col=ready")
        page.wait_for_timeout(300)
        assert page.evaluate("document.body.dataset.col") == "ready"
        # on the tabs, the Area pills, the Group By switch and the New Card form: nothing changes
        for sel in (".coltabs", ".viewrow .pills", ".viewrow .segmented", ".newform", ".coltabs button[data-col=wip]"):
            for dx in (-200, 200):
                got = page.evaluate(SWIPE, [sel, dx])
                assert got == "ready", (sel, dx, got)
        # over the lanes it still works: left is the next column, right the previous
        assert page.evaluate(SWIPE, ["section.lane .lanename", -200]) == "wip"
        assert page.evaluate(SWIPE, ["section.lane .lanename", 200]) == "ready"
        br.close()
    print("swipe tests: all passed")
finally:
    os.killpg(server.pid, 15)
    server.wait()
    shutil.rmtree(work, ignore_errors=True)
