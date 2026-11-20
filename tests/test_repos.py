"""A card's repos (the Machiya frontmatter schema): `repos:` (a list, or names separated by commas) when present, else
`repo:` as a one-entry list; a URL counts as its last segment with `.git` dropped; names compare without regard to case."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from store import parse_note, repo_name, repos_of  # noqa: E402

assert repos_of({"repos": ["Techo", "workshop", "techo", "https://example.com/u/dotfiles.git"]}) == ["Techo", "workshop", "dotfiles"]
assert repos_of({"repos": "techo, workshop ,", "repo": "ignored"}) == ["techo", "workshop"]
assert repos_of({"repo": "git@example.com:user/flynn.git"}) == ["flynn"]
assert repos_of({"repo": "https://git.example.com/user/old-thing/"}) == ["old-thing"]
assert repos_of({"repos": [], "repo": "kept"}) == ["kept"] and repos_of({}) == [] and repos_of({"repo": "a b"}) == []

assert repo_name("https://example.com/u/Kura.git/") == "Kura" and repo_name("") == "" and repo_name(None) == ""
assert repo_name("x" * 100) and not repo_name("x" * 101)

note = "---\ntitle: Workshop\nstatus: wip\nrepo: https://example.com/u/techo\nrepos:\n  - techo\n  - workshop\n  - dotfiles\n---\n# W\n"
card = parse_note(note, "Projects/Workshop.md")
assert card["repos"] == ["techo", "workshop", "dotfiles"] and card["repo"] == "https://example.com/u/techo", card
assert parse_note("---\ntitle: A\nstatus: wip\nrepo: https://example.com/u/a.git\n---\n", "Projects/A.md")["repos"] == ["a"]
assert parse_note("---\ntitle: B\nstatus: wip\n---\n", "Projects/B.md")["repos"] == []
print("repos tests: all passed")
