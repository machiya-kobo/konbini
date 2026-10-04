import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["MACHIYA_ROOMS"] = "shiori=https://shiori.example,konbini=https://konbini.example"
import common, modern
from vaultkit import shell
shell.rooms = lambda env=None: {"shiori": "https://shiori.example", "konbini": "https://konbini.example"}


def card(slug, title, board, **kw):
    c = {"slug": slug, "title": title, "board": board, "area": "tools", "areas": ["tools"], "topics": [], "machines": [],
         "tags": [], "summary": "", "next": "", "blocked_by": "", "waiting": "", "family": "", "stream": "", "goal": "",
         "effort": "", "priority": None, "rank": None, "checks_done": 0, "checks_total": 0, "path": "Projects/%s.md" % title,
         "updated": "2026-09-30", "publish": False}
    c.update(kw); return c


cards = [card("a", "Old Cards", "archived"), card("b", "Backup Plan", "done", summary="nightly copy to a spare disk"),
         card("k", "Kura", "wip", stream="Machiya"), card("s", "Shiori", "ready", goal="Machiya 1.0"),
         card("m", "Machiya Docs", "backlog")]
ctx = common.Ctx("night")
ctx.q = "machiya"
html = modern.search_page(ctx, cards, "machiya", {})
slugs = re.findall(r'data-slug="([^"]+)"', html)
assert slugs == ["m", "s", "k"], slugs                         # title match first, then by column (ready, wip)
assert "3 cards" in html and 'href="https://shiori.example/#/search?q=machiya"' in html
assert html.count('<form class="search') == 1 and 'class="search bar"' in html and html.count('value="machiya"') == 1   # the header's pill is the one field
assert 'class="search' not in html[html.index("<main"):]                  # none in <main>: the page has no field of its own
assert "spare" not in html
html = modern.search_page(ctx, cards, "spare", {})
assert re.findall(r'data-slug="([^"]+)"', html) == ["b"]                           # summary matches
assert "No Matching Cards" in modern.search_page(ctx, cards, "zzz", {})
empty = modern.search_page(common.Ctx("night"), cards, "", {})
assert "Search Cards" in empty and 'class="handoff"' not in empty                 # no hand-off without a query
board = modern.board(common.Ctx("night"), [c for c in cards if c["board"] != "archived"], query={})
assert board.count('class="search bar"') == 1 and 'name="q" value="" placeholder="Search Cards"' in board      # the pill, empty, on every page
# the phone tab bar: Board, Now, Review, Roundup; the desktop nav has no Search item either (the pill is the search)
assert [k for _, k, _ in modern.KANBAN_TABS] == ["board", "now", "review", "roundup"]
assert [k for _, k, _ in modern.KANBAN_NAV] == ["board", "now", "review", "plan", "posts", "calendar", "roundup"]
assert 'class="revlink"' not in modern.now(common.Ctx("night"), [c for c in cards if c["board"] != "archived"], {}, "1")
print("search tests: all passed")
