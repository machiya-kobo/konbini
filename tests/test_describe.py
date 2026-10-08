"""A card's description is note text rendered as data: Markdown through vaultkit's sanitizer. vaultkit 0.29 keeps a class
attribute only when every class is on its allow-list (language-* from fenced code is: board.js draws ```mermaid blocks
from `code.language-mermaid`), and loads remote images by default (Konbini calls sanitize.clean directly)."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ.setdefault("KANBAN_REPO", tempfile.mkdtemp())
import modern

html = modern.describe("A line.\n\n```mermaid\ngraph TD\n  A-->B\n```\n\n```python\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
                       "<p class=\"evil\" onclick=\"x()\">y</p> ![pic](https://example.com/p.png)\n")
assert '<code class="language-mermaid">' in html and '<code class="language-python">' in html, html
assert "<table>" in html and "<td>1</td>" in html, html
assert 'class="evil"' not in html and "onclick" not in html, html           # a class that isn't allowed goes, with the handler
assert 'src="https://example.com/p.png"' in html, html                      # remote images keep loading here (the default)
print("describe tests: all passed")
