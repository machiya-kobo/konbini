# Install Konbini

Every way here starts like the [Quickstart](../README.md#quickstart): clone Konbini and make the sample vault a
repository (steps 1 and 3), then follow your section. Port 8081 must be free. `tools/quickstart-test` runs every
marked block here and in the README from a fresh clone and checks the output.

- [In a container](#in-a-container): Podman or Docker.
- [Natively on the BSDs](#natively-on-the-bsds): OpenBSD, FreeBSD and NetBSD.
- [Check it and drive it with `pm`](#check-it-and-drive-it-with-pm), however it runs.
- [As part of the Machiya stack](#as-part-of-the-machiya-stack).

## In a container

You need `git`, `curl` and either `podman` (4+) or `docker` (24+). Podman on Debian or Ubuntu:

<!-- quickstart: packages-container-debian -->
```bash
sudo apt-get update
sudo apt-get install -y podman git curl
```

*Podman.* `--cgroup-manager=cgroupfs` means podman needs no systemd user session, which a fresh or ssh-only machine
may lack:

<!-- quickstart: container-podman -->
```bash
podman --cgroup-manager=cgroupfs build -t konbini app
podman --cgroup-manager=cgroupfs run -d --init --name konbini-demo -p 127.0.0.1:8081:8081 --userns=keep-id \
  -v "$PWD/demo-vault":/repo -v "$PWD/demo-data":/data -e KANBAN_AUTH=open -e KANBAN_REPO_SUBDIR=personal konbini
```

*Docker.* It runs as your own user, so the mounted folders stay yours:

<!-- quickstart: container-docker -->
```bash
docker build -t konbini app
docker run -d --init --name konbini-demo -p 127.0.0.1:8081:8081 -u "$(id -u):$(id -g)" \
  -v "$PWD/demo-vault":/repo -v "$PWD/demo-data":/data -e KANBAN_AUTH=open -e KANBAN_REPO_SUBDIR=personal konbini
```

## Natively on the BSDs

Python 3.11 or later and `pyyaml` 6+ from packages; `markdown` 3.11+ in a virtual environment (the packaged one is older, and
vaultkit refuses it: one note could exhaust memory). Run the package lines as root or with `doas`/`sudo`. A fresh
OpenBSD has `doas` but no `/etc/doas.conf`; a fresh FreeBSD or NetBSD has no `sudo` (`pkg install sudo`,
`pkg_add sudo`).

OpenBSD's Python uses LibreSSL, which lacks `hashlib.scrypt`. Konbini runs there, but refuses Machiya's identity-file
passwords (`KANBAN_SIGNIN`, pairing codes) with a message saying why. Tokens, Tailscale, header, `open` and `hister` modes work.

*OpenBSD:*

<!-- quickstart: packages-openbsd -->
```bash
doas pkg_add python%3 py3-yaml git curl
```

*FreeBSD.* The packages install a versioned interpreter, so the second line names it `python3`:

<!-- quickstart: packages-freebsd -->
```bash
sudo pkg install -y python312 py312-sqlite3 py312-pyyaml git-lite curl
sudo ln -sf /usr/local/bin/python3.12 /usr/local/bin/python3
```

*NetBSD.* Same again. A fresh NetBSD has no `pkgin`, so this uses `pkg_add` with the release's package repository:

<!-- quickstart: packages-netbsd -->
```bash
sudo env PKG_PATH="https://cdn.NetBSD.org/pub/pkgsrc/packages/NetBSD/$(uname -p)/$(uname -r | cut -d_ -f1)/All" \
  pkg_add python313 py313-yaml git-base curl
sudo ln -sf /usr/pkg/bin/python3.13 /usr/pkg/bin/python3
```

Then, in the clone, the virtual environment (it keeps the packages' PyYAML and adds `markdown` 3.11 or later), the
sample vault (step 3 of the [Quickstart](../README.md#quickstart)) and the run block:

<!-- quickstart: venv-bsd -->
```bash
python3 -m venv --system-site-packages .venv && .venv/bin/pip install -q 'markdown>=3.11'
```

<!-- quickstart: native-run-bsd background -->
```bash
KANBAN_REPO="$PWD/demo-vault" KANBAN_DB="$PWD/demo-data/konbini.sqlite3" \
  KANBAN_AUTH=open KANBAN_BIND=127.0.0.1 KANBAN_REPO_SUBDIR=personal .venv/bin/python app/app.py
```

## Check it and drive it with `pm`

However it runs, this waits up to 30 seconds for the first start (the board indexes the vault) and checks it:

<!-- quickstart: check -->
```bash
for i in $(seq 30); do curl -sf http://127.0.0.1:8081/healthz >/dev/null && break; sleep 1; done
curl -s http://127.0.0.1:8081/healthz
curl -s http://127.0.0.1:8081/api/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print("ok", d["ok"], "cards", d["cards"])'
curl -s http://127.0.0.1:8081/ | grep -o "<title>[^<]*"
```

You should see:

<!-- quickstart-expect: check -->
```text
ok
ok True cards 10
<title>Konbini
```

`tools/pm` is a one-file client (Python 3, no dependencies):

<!-- quickstart: pm -->
```bash
export KANBAN_URL=http://127.0.0.1:8081
python3 tools/pm ls --board wip
python3 tools/pm next led-insert "print the cap holder and test the fit"
git -C demo-vault diff --stat
```

You should see the two cards in progress, then the edit the board made to one note's frontmatter. It commits such
edits to your repository a couple of minutes after the last change.

<!-- quickstart-expect: pm -->
```text
lantern
led-insert
Projects/LED insert.md
1 file changed
```

Stop a container with:

<!-- quickstart: stop-container -->
```bash
podman rm -f konbini-demo 2>/dev/null || docker rm -f konbini-demo
```

A native run stops with Ctrl-C.

## As part of the Machiya stack

[Machiya](https://github.com/machiya-kobo/machiya) runs Konbini, Kura (the notes app) and Niwa (the garden) around one
vault, with Hister and SearXNG as optional search engines. Compared with the Quickstart:

- **Start from Machiya's compose:** `compose/compose.yml`, profile `konbini` (plus `compose/mirror.yml` for a shared
  vault copy). For the sample vault, `compose/demo-init` writes a `.env` and clones a bare copy. For your own, copy
  `compose/.env.example` to `.env` and clone your vault into `KONBINI_REPO`: Konbini needs its own read-write clone
  with a reachable origin. The image builds from this repository's `app/`, expected at `../../konbini` from
  `compose/` (or set `KONBINI_SRC`).
- **Who may use it:** as in [Who can use it](access.md) (`KONBINI_AUTH`, `KONBINI_USERS`). The compose
  defaults to `KANBAN_AUTH=open` for the localhost demo and sets `KANBAN_ALLOWED_HOSTS=konbini`, the name the other
  apps use; keep it if you run Konbini your own way. With the identity file behind the Tailscale sidecar, also set
  `KANBAN_BIND_BEHIND_PROXY=1`.
- **Notes folder:** `KANBAN_REPO_SUBDIR` (`VAULT_SUBDIR` in the compose); the default is the repository root.
- **One vault copy:** `compose/mirror.yml` (or `demo-init --mirror`) points `KANBAN_REPO_REFERENCE` at the mirror's
  checkout (same path in the container) to borrow its git objects, and sets `KANBAN_REPO_SPARSE` to
  `<notes folder>,.board` to check out only what Konbini uses.
- **The other apps:** `KANBAN_KURA_URL` and `KANBAN_NIWA_URL` turn on their links, `KANBAN_BOARD_URL` is this board's
  address, and `MACHIYA_ROOMS` (one value for every app) fills the Rooms menu; the compose passes them from `.env`.
  `MACHIYA_COOKIE_DOMAIN` (e.g. `example.net`) shares the theme and text-size cookies.
- **Source link:** `MACHIYA_SOURCE_URL` adds "Source code" to the footer and About, as the AGPL asks of a network
  service.
- **Settings from a file:** `KANBAN_ENV_FILE` (or `--env-file PATH`) reads `KEY=VALUE` lines first, for a native
  service. See Machiya's [contrib/rc.d/](https://github.com/machiya-kobo/machiya/tree/main/contrib/rc.d) and
  [docs/install/bsd.md](https://github.com/machiya-kobo/machiya/blob/main/docs/install/bsd.md).
