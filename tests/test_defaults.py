"""Neutral defaults: with no settings set, no link points at a tailnet, a blog or an Obsidian vault; with them set,
the links come back."""
import os, re, sys
for k in [k for k in os.environ if k.startswith("KANBAN_") or k == "MACHIYA_ROOMS"]:
    del os.environ[k]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import common, modern, links, writer

card = {"slug": "kura", "title": "Kura", "board": "wip", "area": "tools", "areas": ["tools"], "topics": [], "machines": [],
        "tags": [], "summary": "s", "next": "", "blocked_by": "", "waiting": "", "family": "", "stream": "", "goal": "",
        "due": "", "effort": "", "priority": None, "rank": None, "checks_done": 0, "checks_total": 0,
        "path": "Projects/Kura.md", "updated": "2026-09-30", "publish": False, "repo": "", "dependsOn": [], "post": "", "post_url": ""}
html = modern.detail(common.Ctx("night"), card, [card])
assert "obsidian://" not in html and "View in Kura" not in html and ">Garden<" not in html, "a link without its setting"
assert not re.search(r"\.ts\.net", html), re.findall(r".{40}\.ts\.net.{20}", html)
assert links.UA == "konbini-links/1" and writer.AUTHOR == ("konbini", "konbini@localhost")
assert not links.is_external("https://kura.example.ts.net/n/x") and links.is_external("https://example.org/page")

modern.OBSIDIAN_VAULT, modern.KURA_URL, modern.GARDEN_URL = "my-vault", "https://kura.example", "https://niwa.example"
html = modern.detail(common.Ctx("night"), card, [card])
assert 'href="obsidian://open?vault=my-vault&amp;file=Projects%2FKura"' in html, re.findall(r'obsidian://[^"]*', html)
assert 'href="https://kura.example/n/Projects/Kura"' in html and 'href="https://niwa.example/n/Projects/Kura"' in html
assert '<meta name="obsidian-vault" content="my-vault">' in html
print("defaults tests: all passed")
