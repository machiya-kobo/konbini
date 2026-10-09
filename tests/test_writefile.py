"""A write goes through a temporary file made for it (mkstemp: created exclusively, never through a link), keeps the note's
permissions, and leaves nothing behind when it fails; a link planted where the old fixed temp name was sends nothing
outside the vault; a symlinked note is refused (422); and a stray temp file is never committed."""
import os, stat, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from store import Store
from writer import Writer, WriteError

root = tempfile.mkdtemp(prefix="konbini-writefile-")
vault = root + "/vault"; os.makedirs(vault + "/Projects"); outside = root + "/outside.txt"
open(outside, "w").write("do not touch\n")
NOTE = "---\ntitle: X\ncreated: 2026-02-03\ntags:\n  - type/project\n  - area/projects\nproject: x\nstatus: ready\n---\n# X\n"
open(vault + "/Projects/X.md", "w").write(NOTE)
os.chmod(vault + "/Projects/X.md", 0o640)
git = lambda *a: subprocess.run(["git", "-C", vault, "-c", "user.name=T", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True, text=True).stdout
git("init", "-q", "-b", "main"); git("add", "-A"); git("commit", "-q", "-m", "start")
os.environ["KANBAN_REPO_SUBDIR"] = ""
st = Store(root + "/k.db", vault); st.rebuild()
w = Writer(st)

# a link where the old fixed name was: the write doesn't follow it
for name in ("X.md.kanban-tmp",):
    os.symlink(outside, vault + "/Projects/" + name)
w.update("x", {"board": "wip"}, "me", "test")
assert open(outside).read() == "do not touch\n", "the write followed a link out of the vault"
assert "status: wip" in open(vault + "/Projects/X.md").read()
assert stat.S_IMODE(os.stat(vault + "/Projects/X.md").st_mode) == 0o640, "the note's permissions changed"
left = sorted(n for n in os.listdir(vault + "/Projects") if n.endswith(".kanban-tmp"))
assert left == ["X.md.kanban-tmp"], left                     # only the link this test planted; the write's own is gone

# a new note gets the umask's mode, not mkstemp's 0600
w.write_file("Projects/New.md", "---\nstatus: ready\n---\n# New\n")
umask = os.umask(0); os.umask(umask)
assert stat.S_IMODE(os.stat(vault + "/Projects/New.md").st_mode) == 0o666 & ~umask

# a symlinked note path is refused, and what it points at is left alone
os.symlink(outside, vault + "/Projects/Link.md")
try:
    w.write_file("Projects/Link.md", "overwritten\n"); raise SystemExit("a symlinked note was written")
except WriteError as err:
    assert err.status == 422, err.status
assert open(outside).read() == "do not touch\n"

# a failed write leaves no temp file and the note as it was
real = os.replace
def broken(*a): raise OSError("disk full")
os.replace = broken
try:
    w.write_file("Projects/X.md", "lost\n"); raise SystemExit("no error")
except OSError:
    pass
finally:
    os.replace = real
assert "status: wip" in open(vault + "/Projects/X.md").read()
assert sorted(n for n in os.listdir(vault + "/Projects") if n.endswith(".kanban-tmp")) == ["X.md.kanban-tmp"]

# a stray temp file (a crash mid-write) is never committed, even when the export runs
open(vault + "/Projects/.X.md.abc123.kanban-tmp", "w").write("half a note")
w.commit(force=True)
assert ".kanban-tmp" not in git("ls-files"), git("ls-files")
assert "Projects/X.md" in git("ls-files") and "status: wip" in git("show", "HEAD:Projects/X.md")
print("writefile tests: all passed")
