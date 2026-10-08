"""KANBAN_REPO_SUBDIR: the notes' folder in the repo (default: the repo root); a stub links to no particular note."""
import os, subprocess, sys, tempfile

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
CODE = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
from store import Store, VAULT
from writer import Writer
d = sys.argv[2]
st = Store(d + "/db/k.db", d)
for c in st.scan(): st.upsert(c)
assert VAULT == sys.argv[3], VAULT
assert [c["slug"] for c in st.cards()] == ["one"], st.cards()
st.known_tags = lambda: {"area/projects", "area/tools"}
w = Writer(st)
c = w.create({"title": "Two", "area": "tools"}, "me", "test")
assert os.path.exists("%s/%s/Projects/Two.md" % (d, VAULT)), os.listdir(d)
text = open("%s/%s/Projects/Two.md" % (d, VAULT)).read()
assert "[[Projects/Example" not in text and "[[" not in text and "\n# Two\n" in text, text
w.update("one", {"board": "wip"}, "me", "test")
assert "status: wip" in open("%s/%s/Projects/One.md" % (d, VAULT)).read()
print("ok", VAULT)
'''
NOTE = "---\ntitle: One\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/tools\nproject: one\nstatus: backlog\n---\n# One\n"

def run(subdir, expect):
    d = tempfile.mkdtemp()
    os.makedirs("%s/%s/Projects" % (d, expect))
    open("%s/%s/Projects/One.md" % (d, expect), "w").write(NOTE)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("KANBAN_REPO_SUBDIR", None)
    if subdir is not None:
        env["KANBAN_REPO_SUBDIR"] = subdir
    return subprocess.run([sys.executable, "-c", CODE, APP, d, expect], env=env, capture_output=True, text=True, timeout=60)

for subdir, expect in ((None, ""), ("", ""), (" / ", ""), ("notes", "notes"), (" /vault/notes/ ", "vault/notes")):
    r = run(subdir, expect)
    assert r.returncode == 0 and r.stdout.strip() == ("ok " + expect).strip(), (subdir, r.stdout, r.stderr[-400:])
r = run("../x", "notes")
assert r.returncode != 0 and "KANBAN_REPO_SUBDIR must be a folder inside the repo" in r.stderr, r.stderr[-300:]
print("subdir tests: all passed")
