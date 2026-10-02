"""A fresh install (an empty git repo: no commits, no origin, no settings) starts quietly and makes a first card from
the New-card form; a vault with area/* tags offers exactly those lanes; the kit's blog taxonomy comes from the
optional .board/kit.json, never from code."""
import json, os, re, socket, subprocess, sys, tempfile, textwrap

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
import modern
from kit import Kits

# the form
html = modern.new_form(["docs", "ops", "tools"])
assert '<select name="area"><option value="docs">docs</option><option value="ops">ops</option><option value="tools">tools</option></select>' in html, html
assert "confirm_new_tags" not in html and 'type="text" name="area"' not in html
html = modern.new_form([])
assert 'type="text" name="area"' in html and 'name="confirm_new_tags" value="1"' in html and "<select" not in html, html

# the kit taxonomy
class S:  # the bits of Store that Kits.taxonomy touches
    def __init__(self, repo): self.repo, self.said = repo, []
    def note_once(self, key, msg): self.said.append(key)
d = tempfile.mkdtemp(); os.makedirs(d + "/.board")
st = S(d); kits = Kits(st, None, None, None, "")
EMPTY = {"tag_synonyms": {}, "area_category": {}, "default_category": "", "ignore_tags": [], "ignore_categories": []}
assert kits.taxonomy() == EMPTY and st.said == [], (kits.taxonomy(), st.said)       # no file: empty, silent
open(d + "/.board/kit.json", "w").write(json.dumps({"tag_synonyms": {"shell": "terminal"}, "area_category": {"ops": "hosting"},
                                                    "default_category": "tech", "ignore_tags": ["challenge"], "ignore_categories": ["imported"]}))
assert kits.taxonomy() == {"tag_synonyms": {"shell": "terminal"}, "area_category": {"ops": "hosting"}, "default_category": "tech",
                           "ignore_tags": ["challenge"], "ignore_categories": ["imported"]}
open(d + "/.board/kit.json", "w").write('{"tag_synonyms": ["not", "an", "object"]}')
assert kits.taxonomy() == EMPTY and st.said == ["kit.json"], st.said               # unusable: empty, said once
open(d + "/.board/kit.json", "w").write("{ nope")
assert kits.taxonomy() == EMPTY
src = open(os.path.join(APP, "kit.py")).read()
assert "TAG_SYNONYMS" not in src and "AREA_CATEGORY" not in src

# a running board
HARNESS = textwrap.dedent('''
    import json, sys, threading, time, urllib.request, urllib.error, re
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    port = int(sys.argv[2])
    threading.Thread(target=app.serve, args=(port, "tailnet"), daemon=True).start()
    time.sleep(0.5)
    base = "http://127.0.0.1:%d" % port
    page = urllib.request.urlopen(base + "/", timeout=10).read().decode()
    out = {"form": re.search(r'<form class="newform".*?</form>', page, re.S).group(0)}
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    def post(fields):
        body = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(base + "/new", data=body, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded", "Origin": base, "Host": "127.0.0.1:%d" % port})
        try:
            return urllib.request.build_opener(NoRedirect).open(req, timeout=10).status
        except urllib.error.HTTPError as e:
            return e.code
    import urllib.parse
    out["post"] = post({"title": "First card", "area": "tools", "confirm_new_tags": "1"})
    out["unconfirmed"] = post({"title": "Second card", "area": "ops"}) if len(sys.argv) > 3 else None
    app.writer.commit(force=True); app.writer.pull(); app.writer.pull(); app.writer.ahead()
    out["cards"] = [c["slug"] for c in app.store.cards()]
    out["log"] = open(sys.argv[3]).read() if len(sys.argv) > 3 else ""
    print("RESULT " + json.dumps(out))
''')

def run(repo_setup):
    d = tempfile.mkdtemp(); pass
    subprocess.run(["git", "-C", d, "init", "-q", "-b", "main"], check=True)
    repo_setup(d)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d, KANBAN_DB=d + "/db/k.db", KANBAN_AUTH="open", KANBAN_BIND="127.0.0.1",
               KANBAN_TAILNET_PORT=str(port), PYTHONDONTWRITEBYTECODE="1")
    h = os.path.join(d, "harness.py"); open(h, "w").write(HARNESS)
    r = subprocess.run([sys.executable, h, APP, str(port)], env=env, capture_output=True, text=True, timeout=120)
    lines = [l for l in r.stdout.splitlines() if l.startswith("RESULT ")]
    assert lines, (r.stdout[-600:], r.stderr[-600:])
    return json.loads(lines[-1][7:]), r.stdout + r.stderr

# empty repo: a first-lane box, a first card, and the log says each local-only fact once, with no git failures
out, log = run(lambda d: None)
assert 'type="text" name="area"' in out["form"] and "<select" not in out["form"], out["form"]
assert out["post"] == 302 and out["cards"] == ["first-card"], out
assert not re.search(r"git .* failed", log), log
assert log.count("no commits yet in the vault repo") == 1 and log.count("no origin remote: commits stay local") == 1, log

# a vault with area tags: those lanes, as a select, no free-text box
def vault(d):
    for i, area in enumerate(("tools", "ops", "docs", "projects")):
        open("%s/N%d.md" % (d, i), "w").write("---\ntitle: N%d\ntags:\n  - type/reference\n  - area/%s\n---\n" % (i, area))
out, log = run(vault)
assert re.findall(r'<option value="([^"]+)"', out["form"]) == ["docs", "ops", "projects", "tools"], out["form"]
assert "confirm_new_tags" not in out["form"]
print("fresh tests: all passed")
