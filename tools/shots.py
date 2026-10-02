#!/usr/bin/env python3
"""Screenshots of the board: desktop and iPhone, dark and light.

    python3 tools/shots.py [out_dir] [board_url] [card_slug]

Defaults: <tmp>/konbini-shots, http://127.0.0.1:8081 and the card `example` (pass a board behind a proxy by its
URL, and a slug that exists on it). Against a test container, run tools/tsproxy.py in front of the
listener so the service worker script also gets the identity header, e.g.
`python3 tools/tsproxy.py 18091 18081` and pass http://127.0.0.1:18091.
Needs Playwright for Python with its chromium installed.
"""
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "konbini-shots")
B = (sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8081").rstrip("/")
SLUG = sys.argv[3] if len(sys.argv) > 3 else "example"
os.makedirs(out, exist_ok=True)
errors = []

with sync_playwright() as p:
    br = p.chromium.launch()
    iphone = p.devices["iPhone 13"]

    def shot(name, url, phone=False, scheme="dark", theme=None, before=None, w=1440, h=900):
        kw = dict(iphone) if phone else dict(viewport={"width": w, "height": h}, device_scale_factor=1)
        ctx = br.new_context(color_scheme=scheme, service_workers="allow", **kw)
        if theme:
            ctx.add_cookies([{"name": "theme", "value": theme, "url": B}])
        pg = ctx.new_page()
        pg.on("console", lambda m: errors.append((name, m.type, m.text)) if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errors.append((name, "pageerror", str(e))))
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(700)
        if before:
            before(pg)
        pg.screenshot(path="%s/%s.png" % (out, name))
        ctx.close()

    for theme, scheme in (("night", "dark"), ("day", "light")):
        shot("board-" + theme, B + "/", scheme=scheme, theme=theme)
        shot("card-" + theme, B + "/p/" + SLUG, scheme=scheme, theme=theme)
        shot("ph-board-" + theme, B + "/", phone=True, scheme=scheme, theme=theme)
        shot("ph-card-" + theme, B + "/p/" + SLUG, phone=True, scheme=scheme, theme=theme)
        shot("review-" + theme, B + "/review", scheme=scheme, theme=theme, h=2400)
        shot("ph-review-" + theme, B + "/review", phone=True, scheme=scheme, theme=theme)
    shot("now", B + "/now")
    shot("empty-filter", B + "/?q=zzzznomatch")
    shot("posts", B + "/posts")
    shot("kit", B + "/p/%s/kit" % SLUG)
    shot("calendar", B + "/calendar")
    shot("roundup", B + "/roundup?period=week")
    shot("archived", B + "/archived")
    shot("ph-board-sheet", B + "/", phone=True,
         before=lambda pg: (pg.click(".card:visible .more >> nth=0"), pg.wait_for_timeout(400)))
    shot("ph-now", B + "/now", phone=True)
    shot("ph-calendar", B + "/calendar", phone=True)
    br.close()

print("wrote %s" % out)
print("console errors/warnings: %d" % len(errors))
for e in errors[:20]:
    print("  ", e)
