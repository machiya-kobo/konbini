"""0.28.0, the rename's stage 1 (Hister is now Nogon): KANBAN_NOGON_* is read first and KANBAN_HISTER_* still works
(logged once); a set KANBAN_NOGON_* wins even when empty; KANBAN_AUTH=nogon is hister; /api/status reports `nogon`
beside `hister`; a link copy stored as `nogon` is read like `hister`; the CLI gets the token under both names."""
import json, os, socket, stat, subprocess, sys, tempfile, textwrap, time, urllib.request

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
import hister  # noqa: E402
import links  # noqa: E402

# a link's stored copy named nogon counts like hister (own_urls: the address Nogon stored after a redirect)
l = links.Links(None, None)
l.for_note = lambda rel: [{"url": "https://a.example/", "private_backend": "nogon",
                           "private_url": "http://n/preview?id=https%3A%2F%2Fa.example%2Fafter"},
                          {"url": "https://b.example/", "private_backend": "hister",
                           "private_url": "http://n/preview?id=https%3A%2F%2Fb.example%2Fafter"}]
assert l.own_urls("x") == {"https://a.example/", "https://a.example/after", "https://b.example/",
                           "https://b.example/after"}, l.own_urls("x")

# the CLI gets the token as NOGON__ and HISTER__ (v0.22 reads NOGON__ first); unset, neither is inherited
tmp = tempfile.mkdtemp()
tokfile = os.path.join(tmp, "token")
open(tokfile, "w").write("tok-nogon\n")
cli = os.path.join(tmp, "hister")
out = os.path.join(tmp, "cli.txt")
open(cli, "w").write("#!/bin/sh\nprintf '%%s\\n%%s\\n' \"$NOGON__APP__ACCESS_TOKEN\" \"$HISTER__APP__ACCESS_TOKEN\" > '%s'\n"
                     % out)
os.chmod(cli, os.stat(cli).st_mode | stat.S_IXUSR)
assert hister.Hister("http://127.0.0.1:9", "", cli=cli, token_file=tokfile).index("https://example.com/x")
assert open(out).read().split("\n")[:2] == ["tok-nogon", "tok-nogon"], open(out).read()
os.environ["NOGON__APP__ACCESS_TOKEN"] = "inherited"
assert hister.Hister("http://127.0.0.1:9", "", cli=cli).index("https://example.com/y")
assert open(out).read().split("\n")[:2] == ["", ""], "an inherited NOGON__ token must not reach the CLI"
del os.environ["NOGON__APP__ACCESS_TOKEN"]

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


API = "http://127.0.0.1:9"      # nothing listens: status() reports an error string, never "off"
# the old name still works, and says so once
proc, st = board(KANBAN_HISTER_URL=API)
err = stop(proc)
assert st["hister"] != "off" and st["nogon"] == st["hister"], st
assert err.count("KANBAN_HISTER_URL: an old name, read as KANBAN_NOGON_URL") == 1, err[-800:]
# the new name
proc, st = board(KANBAN_NOGON_URL=API)
err = stop(proc)
assert st["nogon"] != "off" and st["nogon"] == st["hister"] and "an old name" not in err, (st, err[-400:])
# a set KANBAN_NOGON_URL wins even when empty: Nogon is off
proc, st = board(KANBAN_NOGON_URL="", KANBAN_HISTER_URL=API)
stop(proc)
assert st["nogon"] == "off" and st["hister"] == "off", st

# KANBAN_AUTH=nogon is the sign-in mode: without its settings it refuses to start, naming the new setting
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
d = tempfile.mkdtemp()
subprocess.run(["git", "-C", d, "init", "-q"], check=True)
open(d + "/server.py", "w").write(SERVER)
env = {k: v for k, v in os.environ.items() if not k.startswith(("KANBAN_HISTER_", "KANBAN_NOGON_"))}
env.update(KANBAN_REPO=d, KANBAN_DB=d + "/k.db", KANBAN_AUTH="nogon", KANBAN_TAILNET_PORT=str(port),
           KANBAN_BIND="127.0.0.1", KANBAN_BIND_BEHIND_PROXY="1", PYTHONDONTWRITEBYTECODE="1",
           KANBAN_AUTH_SIGNIN_URL="https://login.example.ts.net/machiya/signin",
           KANBAN_BOARD_URL="https://konbini.example.ts.net", KANBAN_AUTH_URL="http://login:8081")
r = subprocess.run([sys.executable, d + "/server.py", APP, str(port)], env=env, capture_output=True, timeout=60)
assert r.returncode != 0 and b"KANBAN_NOGON_USERS" in r.stderr + r.stdout, (r.returncode, r.stderr[-400:])

print("nogon names tests: all passed")
