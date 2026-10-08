"""Every page's text is readable in every palette and mode: 4.5:1 against what it is drawn on (3:1 for large text),
measured in Chromium on the sample vault (tests/contrast.js does the measuring, blending translucent layers). The
shared parts are vaultkit's and tested there; this covers Konbini's own surfaces (lanes, card pages, the calendar,
the action sheet, the outbox badge), where an accent on a raised panel must use its panel shade (vaultkit 0.25).
Needs Playwright for Python with its Chromium; it says so and skips otherwise. KONBINI_CONTRAST_PALETTES=all checks
all ten palettes (the default is two: Tokyo Night and Solarized)."""
import os, signal, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "app"))
from vaultkit import palettes  # noqa: E402

PAGES = ["/", "/now", "/review", "/p/lantern", "/p/lantern-festival-kit", "/p/washi-paper-tests/kit", "/posts",
         "/calendar", "/roundup?period=month", "/streams", "/streams/Lanterns", "/goals", "/timeline", "/deps",
         "/search?q=lantern", "/archived", "/share", "/settings", "/p/old-lantern-restoration"]
PHONE_PAGES = ["/", "/p/lantern", "/calendar"]
WHICH = os.environ.get("KONBINI_CONTRAST_PALETTES", "")
PALETTES = list(palettes.PALETTES) if WHICH == "all" else (WHICH.split(",") if WHICH else ["tokyo-night", "solarized"])
AUDIT = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "contrast.js")).read()

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("contrast tests: skipped (no Playwright for Python)")
    raise SystemExit(0)

work = tempfile.mkdtemp(prefix="konbini-contrast-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
subprocess.run([os.path.join(ROOT, "tools", "demo-vault"), work + "/vault"], check=True, capture_output=True)
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, KANBAN_REPO=work + "/vault", KANBAN_REPO_SUBDIR="personal", KANBAN_DB=work + "/k.db",
           KANBAN_AUTH="open", KANBAN_BIND="127.0.0.1", KANBAN_TAILNET_PORT=str(port), TZ="UTC", PYTHONDONTWRITEBYTECODE="1")
for k in [k for k in env if k.startswith(("KANBAN_NIWA", "KANBAN_KURA", "KANBAN_HISTER", "MACHIYA_"))]:
    del env[k]
env.update(KANBAN_KURA_URL="https://kura.example.ts.net", KANBAN_NIWA_URL="https://niwa.example.ts.net",
           KANBAN_OBSIDIAN_VAULT="vault")        # the card page's link chips (Kura, Niwa, Obsidian) are measured too
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
    failures = []
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception as exc:
            print("contrast tests: skipped (%s)" % str(exc).splitlines()[0][:120])
            raise SystemExit(0)
        for palette in PALETTES:
            for theme, scheme in (("day", "light"), ("night", "dark")):
                for viewport, pages in (({"width": 1280, "height": 900}, PAGES), ({"width": 390, "height": 844}, PHONE_PAGES)):
                    ctx = br.new_context(viewport=viewport, color_scheme=scheme, service_workers="block")
                    ctx.add_cookies([{"name": "theme", "value": theme, "url": BASE},
                                     {"name": "palette", "value": palette, "url": BASE}])
                    ctx.route("**/api/prefs", lambda route: route.abort())     # an open board's shared preferences
                    page = ctx.new_page()
                    for path in pages:
                        page.goto(BASE + path)
                        page.wait_for_timeout(150)
                        page.evaluate("document.querySelectorAll('details').forEach(d => { d.open = true; })")   # Won't do, More, Details
                        for what, got, need in page.evaluate(AUDIT):
                            failures.append("%s %s %s %s: %s %.2f < %g" % (palette, theme, viewport["width"], path, what, got, need))
                        if path == "/" and viewport["width"] == 1280:          # the action sheet and the outbox badge
                            page.click('.card[data-slug="lantern"] .more')
                            for what, got, need in page.evaluate(AUDIT):
                                failures.append("%s %s sheet: %s %.2f < %g" % (palette, theme, what, got, need))
                            page.keyboard.press("Escape")
                    ctx.close()
                # Card Style (Settings): the board's cards are tinted by default; the other styles draw them on other surfaces
                ctx = br.new_context(viewport={"width": 1280, "height": 900}, color_scheme=scheme, service_workers="block")
                ctx.route("**/api/prefs", lambda route: route.abort())
                page = ctx.new_page()
                for style in ("solid", "bar", "none"):
                    ctx.clear_cookies()
                    ctx.add_cookies([{"name": n, "value": v, "url": BASE} for n, v in
                                     (("theme", theme), ("palette", palette), ("cardStyle", style))])
                    for path in ("/", "/now", "/review", "/p/lantern"):
                        page.goto(BASE + path)
                        page.wait_for_timeout(150)
                        assert page.evaluate("document.body.dataset.cardStyle") == style, (path, style)
                        for what, got, need in page.evaluate(AUDIT):
                            failures.append("%s %s card style %s %s: %s %.2f < %g" % (palette, theme, style, path, what, got, need))
                ctx.close()
        br.close()
    if failures:
        print("\n".join(sorted(set(failures))))
        raise AssertionError("%d contrast failures" % len(set(failures)))
    print("contrast tests: all passed (%s)" % ", ".join(PALETTES))
finally:
    try:
        os.killpg(server.pid, signal.SIGTERM)
    except OSError:
        pass
