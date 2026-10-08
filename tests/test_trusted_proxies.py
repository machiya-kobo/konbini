"""KANBAN_TRUSTED_PROXIES: an identity header (Tailscale-User-Login and the others, KANBAN_AUTH_HEADER) counts only on a
connection from one of the listed peers; from anyone else it is dropped before the gate reads it, so the request is
anonymous. A mode that believes the header (tailscale, header, or hister with its tailscale fallback) on a bind that
isn't loopback refuses to start without the setting."""
import os, socket, subprocess, sys, tempfile, textwrap, time, urllib.error, urllib.request

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
import ipaddress  # noqa: E402

# -- parsing and matching (app.py is imported with the loopback defaults the suite runs with) -------------------------
_tmp = tempfile.mkdtemp()
os.environ.update(KANBAN_BIND="127.0.0.1", KANBAN_AUTH="open", KANBAN_REPO=_tmp, KANBAN_DB=_tmp + "/k.db")
import app  # noqa: E402

assert app.trusted_proxies("") == () and app.trusted_proxies(None) == ()
nets = app.trusted_proxies("10.210.4.2/32, fd00::/8 ,127.0.0.1")
assert nets == (ipaddress.ip_network("10.210.4.2/32"), ipaddress.ip_network("fd00::/8"), ipaddress.ip_network("127.0.0.1/32"))
for bad in ("nonsense", "10.0.0.0/33", "10.0.0.1;10.0.0.2"):
    try:
        app.trusted_proxies(bad)
        raise SystemExit("accepted %r" % bad)
    except SystemExit as exc:
        assert "KANBAN_TRUSTED_PROXIES" in str(exc), exc
assert app.peer_trusted("10.1.2.3", ()) is True                                    # none set: every peer, as before
assert app.peer_trusted("10.210.4.2", nets) and not app.peer_trusted("10.210.4.3", nets)
assert app.peer_trusted("::ffff:127.0.0.1", nets) and app.peer_trusted("fd00::1", nets)    # an IPv4 peer seen through IPv6
assert app.peer_trusted("fe80::1%eth0", app.trusted_proxies("fe80::/10"))          # a scope id is not part of the address
assert not app.peer_trusted("", nets) and not app.peer_trusted("not an address", nets)

# -- start-up: the header-trusting modes on a public bind -----------------------------------------------------------
START = "import sys; sys.path.insert(0, sys.argv[1]); import app; print('started')"
HISTER = dict(KANBAN_AUTH="hister", KANBAN_AUTH_SIGNIN_URL="https://login.example.ts.net/signin",
              KANBAN_AUTH_URL="http://hister-login:8081", KANBAN_HISTER_USERS="owner",
              KANBAN_BOARD_URL="https://konbini.example.ts.net", KANBAN_TAILNET_USERS="owner@example.com")


def boot(**env):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("KANBAN_", "MACHIYA_"))}
    d = tempfile.mkdtemp()
    base.update(KANBAN_REPO=d, KANBAN_DB=d + "/k.db", PYTHONDONTWRITEBYTECODE="1")
    base.update(env)
    return subprocess.run([sys.executable, "-c", START, APP], env=base, capture_output=True, text=True, timeout=60)


def refused(r):
    return r.returncode != 0 and "KANBAN_TRUSTED_PROXIES" in r.stderr


assert refused(boot(KANBAN_BIND="0.0.0.0")), "tailscale mode (the default) on a public bind"
assert boot(KANBAN_BIND="0.0.0.0", KANBAN_TRUSTED_PROXIES="10.210.4.2/32").returncode == 0
assert boot(KANBAN_BIND="127.0.0.1").returncode == 0 and boot(KANBAN_BIND="::1").returncode == 0     # behind `tailscale serve`
assert boot(KANBAN_BIND="0.0.0.0", KANBAN_AUTH="open").returncode == 0                # open reads no header
assert refused(boot(KANBAN_BIND="0.0.0.0", KANBAN_BIND_BEHIND_PROXY="1", **HISTER)), "hister with its tailscale fallback"
assert boot(KANBAN_BIND="0.0.0.0", KANBAN_BIND_BEHIND_PROXY="1", KANBAN_TRUSTED_PROXIES="10.210.4.2/32", **HISTER).returncode == 0
assert boot(KANBAN_BIND="0.0.0.0", KANBAN_BIND_BEHIND_PROXY="1", KANBAN_AUTH_FALLBACK="none", **HISTER).returncode == 0   # no header read
r = boot(KANBAN_BIND="127.0.0.1", KANBAN_TRUSTED_PROXIES="not-an-address")
assert r.returncode != 0 and "not an address or network" in r.stderr, r.stderr[-300:]

# -- a running board: the header counts from a trusted peer only ----------------------------------------------------
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
procs = []


def start(**extra):
    d = tempfile.mkdtemp(dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
    os.makedirs(d + "/vault/Projects")
    open(d + "/vault/Projects/Kura.md", "w").write("---\ntitle: Kura\ntags:\n  - type/project\n  - area/projects\nstatus: wip\n---\n# Kura\n")
    subprocess.run(["git", "-C", d + "/vault", "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KANBAN_", "MACHIYA_"))}
    env.update(KANBAN_REPO=d + "/vault", KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_PORT=str(port), KANBAN_BIND="127.0.0.1",
               KANBAN_AUTH="tailscale", KANBAN_TAILNET_USERS="owner@example.com", PYTHONDONTWRITEBYTECODE="1")
    env.update(extra)
    open(d + "/server.py", "w").write(SERVER)
    procs.append(subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env, stdout=subprocess.DEVNULL,
                                  stderr=open(d + "/server.log", "w")))
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return port
        except OSError:
            time.sleep(0.05)
    raise SystemExit("board did not start: " + open(d + "/server.log").read()[-500:])


def status(port, headers):
    req = urllib.request.Request("http://127.0.0.1:%d/api/cards" % port, headers=dict({"Host": "127.0.0.1:%d" % port}, **headers))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as err:
        return err.code


OWNER = {"Tailscale-User-Login": "owner@example.com"}
try:
    plain = start()                                                                  # unset: every peer's header counts, as before
    assert status(plain, OWNER) == 200 and status(plain, {}) == 403
    trusted = start(KANBAN_TRUSTED_PROXIES="10.99.0.1/32, 127.0.0.1")                # this test's peer (127.0.0.1) is listed
    assert status(trusted, OWNER) == 200 and status(trusted, {}) == 403
    stranger = start(KANBAN_TRUSTED_PROXIES="10.99.0.1/32")                          # it isn't: the header is dropped
    assert status(stranger, OWNER) == 403, "an untrusted peer's Tailscale-User-Login must not count"
    assert status(stranger, dict(OWNER, **{"Tailscale-App-Capabilities": "{}", "Remote-User": "owner@example.com"})) == 403
    print("trusted proxies tests: all passed")
finally:
    for p in procs:
        p.kill()
