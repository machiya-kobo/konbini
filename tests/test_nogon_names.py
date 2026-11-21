"""0.30.0, the rename's stage 3 (Hister is now Nogon): only KANBAN_NOGON_* is read. An old KANBAN_HISTER_* name on its own
stops the board with a message naming the new one (no traceback); beside its new name it is ignored and said once; a set
KANBAN_NOGON_* wins even when empty; KANBAN_AUTH=hister stops the board (use nogon); /api/status reports `nogon` and no
`hister`; a link copy stored as `nogon` or `hister` is read alike; the CLI gets the token as NOGON__ only."""
import json, os, socket, stat, subprocess, sys, tempfile, textwrap, time, urllib.request

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
import nogon  # noqa: E402
import links  # noqa: E402

# a link's stored copy named nogon or hister counts alike (own_urls: the address Nogon stored after a redirect); the
# stored value stays "hister" (stored names stay)
assert links.NogonBackend.name == "hister"
l = links.Links(None, None)
l.for_note = lambda rel: [{"url": "https://a.example/", "private_backend": "nogon",
                           "private_url": "http://n/preview?id=https%3A%2F%2Fa.example%2Fafter"},
                          {"url": "https://b.example/", "private_backend": "hister",
                           "private_url": "http://n/preview?id=https%3A%2F%2Fb.example%2Fafter"}]
assert l.own_urls("x") == {"https://a.example/", "https://a.example/after", "https://b.example/",
                           "https://b.example/after"}, l.own_urls("x")

# the CLI gets the token as NOGON__ only (v0.22); unset, neither name is inherited
tmp = tempfile.mkdtemp()
tokfile = os.path.join(tmp, "token")
open(tokfile, "w").write("tok-nogon\n")
cli = os.path.join(tmp, "nogon")
out = os.path.join(tmp, "cli.txt")
open(cli, "w").write("#!/bin/sh\nprintf '%%s\\n%%s\\n' \"$NOGON__APP__ACCESS_TOKEN\" \"${HISTER__APP__ACCESS_TOKEN-unset}\" > '%s'\n"
                     % out)
os.chmod(cli, os.stat(cli).st_mode | stat.S_IXUSR)
assert nogon.Nogon("http://127.0.0.1:9", "").cli == "nogon"
assert nogon.Nogon("http://127.0.0.1:9", "", cli=cli, token_file=tokfile).index("https://example.com/x")
assert open(out).read().split("\n")[:2] == ["tok-nogon", "unset"], open(out).read()
os.environ["NOGON__APP__ACCESS_TOKEN"] = os.environ["HISTER__APP__ACCESS_TOKEN"] = "inherited"
assert nogon.Nogon("http://127.0.0.1:9", "", cli=cli).index("https://example.com/y")
assert open(out).read().split("\n")[:2] == ["", "unset"], "an inherited token must not reach the CLI"
del os.environ["NOGON__APP__ACCESS_TOKEN"], os.environ["HISTER__APP__ACCESS_TOKEN"]

# a running board under each spelling
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')


def board(**names):
    d = tempfile.mkdtemp()
    os.makedirs(d + "/Projects")
    open(d + "/Projects/Kura.md", "w").write("---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n"
                                              "  - area/projects\nproject: kura\nstatus: wip\n---\n# Kura\n")
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KANBAN_HISTER_", "KANBAN_NOGON_"))}
    env.update(KANBAN_REPO=d, KANBAN_DB=d + "/db/k.db", KANBAN_AUTH="open", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", PYTHONDONTWRITEBYTECODE="1", **names)
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    for _ in range(200):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/status" % port, timeout=2) as r:
                return proc, json.loads(r.read())
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise AssertionError("the board never answered: %s" % proc.stderr.read().decode()[-500:])


def stop(proc):
    proc.terminate()
    try:
        _, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
    return err.decode()


def start(**extra):
    """Run the board with these settings until it exits (it should refuse to start): (returncode, stderr+stdout)."""
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    d = tempfile.mkdtemp()
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    open(d + "/server.py", "w").write(SERVER)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KANBAN_HISTER_", "KANBAN_NOGON_", "KANBAN_AUTH"))}
    env.update(KANBAN_REPO=d, KANBAN_DB=d + "/k.db", KANBAN_AUTH="open", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", PYTHONDONTWRITEBYTECODE="1")
    env.update(extra)
    r = subprocess.run([sys.executable, d + "/server.py", APP, str(port)], env=env, capture_output=True, text=True,
                       timeout=60)
    return r.returncode, r.stderr + r.stdout


API = "http://127.0.0.1:9"      # nothing listens: status() reports an error string, never "off"
# each old name on its own stops the board, naming the new one, with no traceback
for old in ("KANBAN_HISTER_URL", "KANBAN_HISTER_PUBLIC", "KANBAN_HISTER_SAVE", "KANBAN_HISTER_TOKEN_FILE"):
    code, err = start(**{old: API if old == "KANBAN_HISTER_URL" else "1"})
    new = old.replace("HISTER", "NOGON")
    assert code != 0 and ("konbini: %s is an old name and is no longer read: rename it %s" % (old, new)) in err, (old, code, err[-600:])
    assert "Traceback" not in err, err[-800:]
# KANBAN_AUTH=hister stops the board too: use nogon
code, err = start(KANBAN_AUTH="hister")
assert code != 0 and "konbini: KANBAN_AUTH=hister is an old name and is no longer read: use KANBAN_AUTH=nogon" in err, err[-600:]
assert "Traceback" not in err, err[-800:]
# KANBAN_HISTER_USERS alone in nogon mode: refused, naming the new one
code, err = start(KANBAN_AUTH="nogon", KANBAN_HISTER_USERS="owner", KANBAN_BIND_BEHIND_PROXY="1",
                  KANBAN_AUTH_SIGNIN_URL="https://login.example.ts.net/machiya/signin",
                  KANBAN_BOARD_URL="https://konbini.example.ts.net", KANBAN_AUTH_URL="http://login:8081")
assert code != 0 and "KANBAN_NOGON_USERS" in err and "Traceback" not in err, err[-600:]

# the new name; status has no "hister" twin
proc, st = board(KANBAN_NOGON_URL=API)
err = stop(proc)
assert st["nogon"] != "off" and "hister" not in st and "an old name" not in err, (st, err[-400:])
# an old name beside its new one is ignored, and said once
proc, st = board(KANBAN_NOGON_URL=API, KANBAN_HISTER_URL="http://127.0.0.1:8")
err = stop(proc)
assert st["nogon"]["api"] == API, st
assert err.count("KANBAN_HISTER_URL: an old name, ignored (KANBAN_NOGON_URL is set") == 1, err[-800:]
# a set KANBAN_NOGON_URL wins even when empty: Nogon is off
proc, st = board(KANBAN_NOGON_URL="", KANBAN_HISTER_URL=API)
stop(proc)
assert st["nogon"] == "off" and "hister" not in st, st

# KANBAN_AUTH=nogon is the sign-in mode: without its settings it refuses to start, naming the new setting
code, err = start(KANBAN_AUTH="nogon", KANBAN_BIND_BEHIND_PROXY="1",
                  KANBAN_AUTH_SIGNIN_URL="https://login.example.ts.net/machiya/signin",
                  KANBAN_BOARD_URL="https://konbini.example.ts.net", KANBAN_AUTH_URL="http://login:8081")
assert code != 0 and "KANBAN_NOGON_USERS" in err, (code, err[-400:])

print("nogon names tests: all passed")
