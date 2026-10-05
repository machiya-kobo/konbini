# konbini

A kanban board (Konbini) built from an Obsidian vault's frontmatter, driven by people and scripts (including AI
agents) over a small HTTP API, installable on a phone. It is part of
[Machiya](https://github.com/machiya-kobo/machiya), a small stack of services around a vault of notes; the garden (Niwa) and
the note reader (Kura) are its sister services, and Shiori is its search app. All of them are optional: Konbini runs
alone.

- The notes are the source of truth; SQLite is a cache; git is the backup.
- Cards are notes whose `status:` is a board column (backlog, ready, wip, blocked, done, archived).
- Every card gets a writing kit: the facts of a finished project, laid out for a blog post.
- `/api/cards` and `/api/digest` feed Niwa's column badges and the board half of its stream.

## Quickstart

Konbini alone on your own machine, with the sample vault (a paper-lantern workshop and a trip to Kyoto: ten cards, three
streams, two goals): no account, no Tailscale, no identity file. You need Python 3.11 or newer, `git` and `curl`; these
are the commands for Debian or Ubuntu, and other systems and containers are under "More ways to run it":

<!-- quickstart: packages-debian -->
```bash
sudo apt update
sudo apt install -y python3 python3-venv git curl
```

**1. Clone Konbini:**

```sh
git clone https://github.com/machiya-kobo/konbini.git && cd konbini
```

**2. Install its two Python packages** (`markdown` and `pyyaml`) in a virtual environment:

<!-- quickstart: native-install-debian -->
```bash
python3 -m venv .venv
.venv/bin/pip install markdown pyyaml
```

**3. Make the sample vault a git repository.** Konbini commits its edits to the vault, so the demo copy has to be one;
its notes are in `personal/`:

<!-- quickstart: vault -->
```bash
tools/demo-vault demo-vault
mkdir -p demo-data
```

**4. Start it** on `127.0.0.1:8081` with the identity check off (`KANBAN_AUTH=open`, for your own machine only):

<!-- quickstart: native-run-debian background -->
```bash
KANBAN_REPO="$PWD/demo-vault" KANBAN_DB="$PWD/demo-data/konbini.sqlite3" \
  KANBAN_AUTH=open KANBAN_BIND=127.0.0.1 KANBAN_REPO_SUBDIR=personal .venv/bin/python app/app.py
```

**5. Open <http://127.0.0.1:8081/>**: ten cards across the board's columns, and the header leads to Board, Now,
Review, Plan, Posts, Calendar and Roundup, with a search field for the cards. Ctrl-C stops it; `rm -rf demo-vault demo-data .venv` cleans up.

`tools/quickstart-test` runs these steps (and the checks, `pm` and the other systems below) from a fresh clone and checks
the output.

## Who can use it

- **You, on localhost:** `KANBAN_AUTH=open` with `KANBAN_BIND=127.0.0.1`, as in the Quickstart: no login, and Konbini
  answers only to an IP address, `localhost`, `KANBAN_BOARD_URL`'s host or a name in `KANBAN_ALLOWED_HOSTS`.
- **People on your tailnet:** bind `127.0.0.1`, put `tailscale serve` in front, and list their Tailscale logins in
  `KANBAN_TAILNET_USERS` (`KANBAN_AUTH=tailscale`, the default; unset = nobody).
- **People, agents, sign-in or Shiori devices:** turn on Machiya's identity file with `cd app && python3 -m vaultkit.identity setup` (the command is the vendored
  vaultkit, standard library only), which prints the settings for each room. It's off unless you set it; see [Machiya's identity guide](https://github.com/machiya-kobo/machiya/blob/main/docs/identity.md).
- **People signed in to Hister:** `KANBAN_AUTH=hister` with Machiya's hister-login helper (`KANBAN_AUTH_SIGNIN_URL`, `KANBAN_AUTH_URL`,
  `KANBAN_HISTER_USERS`, `KANBAN_BOARD_URL`; see [Machiya's Hister sign-in](https://github.com/machiya-kobo/machiya/blob/main/docs/identity.md#hister-sign-in-authhister)).
  Not with an identity file.
- Konbini's identity settings: `MACHIYA_IDENTITY_FILE`, `KANBAN_SIGNIN`, `KANBAN_AUTH_HEADER`,
  `KANBAN_BIND_BEHIND_PROXY`, `KANBAN_ACCEPT_APP_CAPS` and `KANBAN_BOARD_URL` (under Settings).

## More ways to run it

Install the packages each one names first, then do steps 1 and 3 of the Quickstart (clone Konbini, make the sample vault a repository), then start it. Port 8081 must be free.

### In a container

You need `git`, `curl` and one of `podman` (4 or newer) or `docker` (24 or newer; install it with your system's own
instructions). On Debian or Ubuntu, podman:

<!-- quickstart: packages-container-debian -->
```bash
sudo apt update
sudo apt install -y podman git curl
```

*Container with podman* (`--cgroup-manager=cgroupfs` keeps podman from needing a systemd user session, which a freshly set-up or ssh-only machine may not have yet):

<!-- quickstart: container-podman -->
```bash
podman --cgroup-manager=cgroupfs build -t konbini app
podman --cgroup-manager=cgroupfs run -d --init --name konbini-demo -p 127.0.0.1:8081:8081 --userns=keep-id \
  -v "$PWD/demo-vault":/repo -v "$PWD/demo-data":/data -e KANBAN_AUTH=open -e KANBAN_REPO_SUBDIR=personal konbini
```

*Container with docker* (it runs as your own user, so the mounted folders stay yours):

<!-- quickstart: container-docker -->
```bash
docker build -t konbini app
docker run -d --init --name konbini-demo -p 127.0.0.1:8081:8081 -u "$(id -u):$(id -g)" \
  -v "$PWD/demo-vault":/repo -v "$PWD/demo-data":/data -e KANBAN_AUTH=open -e KANBAN_REPO_SUBDIR=personal konbini
```

### Natively on the BSDs

Python 3.11 or newer with `markdown` 3.11+ (older ones are refused: a single note can exhaust memory) and `pyyaml` 6+, from packages only, no pip (if your system's `markdown` is older, use a virtual environment and pip). Install them (as root, or with `doas` or `sudo` set up: a fresh OpenBSD has `doas` but no `/etc/doas.conf`, and a fresh FreeBSD or NetBSD has no `sudo`; `pkg install sudo` or `pkg_add sudo`, or run the line as root without the prefix):

**OpenBSD:** its Python is built against LibreSSL, which has no `hashlib.scrypt`. Konbini starts there (vaultkit 0.21 no longer needs it at import); only the password parts of Machiya's identity file (the built-in sign-in `KANBAN_SIGNIN`, pairing codes) are refused, with a message that says why. Tokens, Tailscale, header, `open` and `hister` modes work.

*OpenBSD:*

<!-- quickstart: packages-openbsd -->
```bash
doas pkg_add python%3 py3-markdown py3-yaml git curl
```

*FreeBSD* (the packages install a versioned interpreter, so the second line gives it the name `python3` used below):

<!-- quickstart: packages-freebsd -->
```bash
sudo pkg install -y python312 py312-sqlite3 py312-markdown py312-pyyaml git-lite curl
sudo ln -sf /usr/local/bin/python3.12 /usr/local/bin/python3
```

*NetBSD* (same; a fresh NetBSD has no `pkgin`, so this uses `pkg_add` with the release's package repository):

<!-- quickstart: packages-netbsd -->
```bash
sudo env PKG_PATH="https://cdn.NetBSD.org/pub/pkgsrc/packages/NetBSD/$(uname -p)/$(uname -r | cut -d_ -f1)/All" \
  pkg_add python313 py313-markdown py313-yaml git-base curl
sudo ln -sf /usr/pkg/bin/python3.13 /usr/pkg/bin/python3
```

Then start it:

<!-- quickstart: native-run-bsd background -->
```bash
KANBAN_REPO="$PWD/demo-vault" KANBAN_DB="$PWD/demo-data/konbini.sqlite3" \
  KANBAN_AUTH=open KANBAN_BIND=127.0.0.1 KANBAN_REPO_SUBDIR=personal python3 app/app.py
```

### Check it and drive it with `pm`

Whichever way it runs, this waits up to 30 seconds for the first start (the board indexes the vault) and checks it:

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

You should see the two cards in progress, then the edit the board made to one note's frontmatter (it commits such edits
to your repository a couple of minutes after the last change):

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

### As part of the Machiya stack

[Machiya](https://github.com/machiya-kobo/machiya) runs Konbini, Kura (the note reader) and Niwa (the garden) around one
vault, with Hister and SearXNG as optional search engines. What changes compared with the Quickstart:

- **Start from the reference compose** in the Machiya repository (`compose/compose.yml`, profile `konbini`, plus
  `compose/mirror.yml` for a shared vault copy) instead of the commands above. With the sample vault, run its
  `compose/demo-init` (it writes a `.env` and makes Konbini's clone of a bare copy of the vault); with your own vault,
  copy `compose/.env.example` to `.env`, edit it, and clone your vault into `KONBINI_REPO` first (Konbini needs its own
  read-write clone, and its origin must be reachable so the board can push). The compose builds the image from this
  repository's `app/` (it expects this clone next to the Machiya clone, `../../konbini` from `compose/`, or set `KONBINI_SRC`).
- **Who may use it:** as in "Who can use it" above (`KONBINI_AUTH` and `KONBINI_USERS` in the compose). The reference
  compose defaults to `KANBAN_AUTH=open` for the localhost demo and sets `KANBAN_ALLOWED_HOSTS=konbini` (the name the other rooms call Konbini by); keep that if you run it your own way. With the identity file behind the Tailscale sidecar, also set
  `KANBAN_BIND_BEHIND_PROXY=1`.
- **Notes folder.** If the vault keeps its notes in a folder, set `KANBAN_REPO_SUBDIR` (`VAULT_SUBDIR` in the compose);
  the default is the repository root.
- **One vault copy.** `compose/mirror.yml` (or `demo-init --mirror`) keeps a single shared copy of the vault: it sets
  `KANBAN_REPO_REFERENCE` to the mirror's checkout (mounted at the same path in the container) so Konbini borrows its
  git objects, and `KANBAN_REPO_SPARSE` to `<notes folder>,.board` so it checks out only what it reads and writes (see
  "Stack mode" in `CLAUDE.md`).
- **The other rooms.** Set `KANBAN_KURA_URL` and `KANBAN_NIWA_URL` to their addresses to get "View in Kura" and the
  garden links, `KANBAN_BOARD_URL` to this board's own address, and `MACHIYA_ROOMS` (the same value in every room) for
  the Rooms switcher; the compose passes all of them from its `.env`. `MACHIYA_COOKIE_DOMAIN` (for example `example.net`) shares the theme and text-size cookies across
  the rooms.
- **Source link.** Set `MACHIYA_SOURCE_URL` to where this room's source is published to add a "Source code" link to the
  footer and the About page (the AGPL asks for it when people use a service over a network).
- **Settings from a file.** `KANBAN_ENV_FILE` (or `--env-file PATH`) reads `KEY=VALUE` lines first, for a native
  service (the rc.d scripts are in the Machiya repository's [contrib/rc.d/](https://github.com/machiya-kobo/machiya/tree/main/contrib/rc.d) and the guide in [docs/install/bsd.md](https://github.com/machiya-kobo/machiya/blob/main/docs/install/bsd.md)).

## Screenshots

All taken from the sample vault (`tools/screenshots` makes them again).

| | Light | Dark |
|---|---|---|
| The board | ![Board, light](docs/screenshots/konbini-board-light.png) | ![Board, dark](docs/screenshots/konbini-board-dark.png) |
| A card | ![A card, light](docs/screenshots/konbini-card-light.png) | ![A card, dark](docs/screenshots/konbini-card-dark.png) |
| The weekly review | ![Review, light](docs/screenshots/konbini-review-light.png) | ![Review, dark](docs/screenshots/konbini-review-dark.png) |

On a phone, the board and a card:

![Board on a phone](docs/screenshots/konbini-board-phone-light.png) ![A card on a phone](docs/screenshots/konbini-card-phone-light.png)

## Settings

| Setting | Default | |
|---|---|---|
| `KANBAN_ENV_FILE` (or `--env-file PATH`) | — | native installs (e.g. BSD rc.d): read these settings from a file of `KEY=VALUE` lines first; the real environment wins. A missing or bad file stops start-up, naming the file and line |
| `KANBAN_AUTH` | `tailscale` | `tailscale`: every page and write needs a `Tailscale-User-Login` in `KANBAN_TAILNET_USERS` (or, with an identity file, a principal the file names). `open`: no identity check (a startup warning), for localhost or a trusted LAN only; the identity header is ignored and writes are logged as `local`. `header` (only with `MACHIYA_IDENTITY_FILE`): a trusted proxy's login header (`KANBAN_AUTH_HEADER`). `hister`: Hister's users are the sign-in (see the Hister sign-in rows below; never with an identity file). Either way, form posts must be same-origin, and an API write from outside the board's pages must send `X-Agent` and no cross-site `Origin` or `Referer` (CSRF; 403 otherwise). Any other value refuses to start |
| `KANBAN_ALLOWED_HOSTS` | — | with `KANBAN_AUTH=open`: the host names the board answers to, comma-separated (case, port and a trailing dot don't matter), on top of IP addresses, `localhost` and `KANBAN_BOARD_URL`'s host. Any other `Host` gets 403, so a web page can't reach the board by pointing its own name at your machine (DNS rebinding). Ignored with `tailscale` |
| `KANBAN_TAILNET_USERS` | — | allowed `Tailscale-User-Login`s, comma-separated; unset = nobody (with `KANBAN_AUTH=tailscale`). Not used with an identity file |
| `MACHIYA_IDENTITY_FILE` | — | Machiya's identity file (vaultkit's `identity`; [Machiya's `docs/identity.md`](https://github.com/machiya-kobo/machiya/blob/main/docs/identity.md)): people, agents and services with grants. Set, it replaces `KANBAN_TAILNET_USERS` and the `X-Agent` test for owner powers: every page and read API needs the `konbini` `read` grant, every change (card edits, comments, claims, the board's forms) `write`, and new `area/*` lanes and new tags `areas`. No proof or a bad one gets 401, a missing grant 403; an event's actor is the principal (`X-Agent` stays a label). With `KANBAN_AUTH=open` a request without a token is the owner. Mount the file's directory read-only (not the file: the CLI replaces it, and a file mount keeps the old one) |
| `KANBAN_SIGNIN` | — | `1`, with an identity file: the built-in sign-in (a person's name and password from the file, a `machiya_session` cookie; see "Sign-in, pairing and preferences" below). A browser without a session then gets a 401 page linking to `/signin?next=<the page>`. Behind an https proxy leave `KANBAN_BOARD_URL` https or unset; on plain http set it to the board's `http://` address, or every sign-in is refused (403) |
| `KANBAN_AUTH_HEADER` | — | with an identity file and `KANBAN_AUTH=header`: the trusted proxy's login header (`Remote-User`, …), matched against the principals' `proxy` logins |
| `KANBAN_BIND_BEHIND_PROXY` | — | `1`: a proxy (the Tailscale sidecar) is the only way in, so a header-trusting mode may bind a non-loopback address. It applies with an identity file (`KANBAN_AUTH=tailscale` or `header`) and with `KANBAN_AUTH=hister` (its `tailscale` fallback); in those modes, without it, the board refuses to start on anything but a loopback address. Plain `tailscale` mode without an identity file doesn't check the bind (see `KANBAN_BIND`) |
| `KANBAN_AUTH_SIGNIN_URL` | — | with `KANBAN_AUTH=hister` (required): the hister-login helper's public sign-in page, where a signed-out page is sent (it comes back to the page it left; at most one trip per 30 s per browser, then a page with a link). With `KANBAN_HISTER_USERS`, `KANBAN_BOARD_URL` and `KANBAN_AUTH_URL` this is the whole of [Machiya's Hister sign-in](https://github.com/machiya-kobo/machiya/blob/main/docs/identity.md#hister-sign-in-authhister) |
| `KANBAN_AUTH_URL` | — | with `KANBAN_AUTH=hister`: the helper's internal address (`http://hister-login:8081`), which the board asks who is calling. Unset: Konbini runs on the tailnet login alone, with a start-up warning (with `KANBAN_AUTH_FALLBACK=none` it refuses to start) |
| `KANBAN_HISTER_USERS` | — | with `KANBAN_AUTH=hister` (required): the Hister usernames admitted, comma-separated, never `*`. Another Hister account is refused (403), never passed on to the fallback |
| `KANBAN_AUTH_FALLBACK` | `tailscale` | with `KANBAN_AUTH=hister`: what happens when sign-in is unavailable (the helper or Hister unreachable, a 5xx, or Hister's user handling off). `tailscale`: the `Tailscale-User-Login`s in `KANBAN_TAILNET_USERS` are admitted as the owner, with a banner; `none`: 503. Someone who is simply signed out is never let in this way. `KANBAN_BOARD_URL` is required in this mode (the way back). `/api/health`, `/api/status` and `/api/changelog` answer without a sign-in, so probes and the status page keep working (the owner sees the full health). Sign out is `POST /signout` (same-origin). A headless client (`pm`, a script, the MCP) sends a room token the helper minted for Konbini as `Authorization: Bearer mht_…` (`pm`: `KANBAN_TOKEN_FILE`), or the owner's Hister token as `X-Access-Token`. Browsers get their own host-only cookie per room (`__Host-machiya_sso_konbini`, a room session the helper hands over once through `/machiya/callback`); `MACHIYA_COOKIE_DOMAIN` is no longer needed for sign-in |
| `KANBAN_AUTH_ACCEPT_ORIGINS` | — | with `KANBAN_AUTH=hister`: other origins (`https://host[:port]`, comma-separated, nothing after the host) whose room sessions this board also accepts: the hosted Shiori pages, whose own proxy passes their room cookie on. Every check the board makes names its own origin first, then these |
| `MACHIYA_SSO_COOKIE` | `machiya_sso` | with `KANBAN_AUTH=hister`: the name of the Hister sign-in cookie; set the same value in the hister-login helper and every room. Only for a second stack under the same cookie domain (a dev stack, say). Letters, digits, `_` and `-` |
| `KANBAN_ACCEPT_APP_CAPS` | — | `1`: read Tailscale's forwarded app capability (`Tailscale-App-Capabilities`) for tagged nodes. Only where Serve forwards it (`--accept-app-caps`, Tailscale v1.92+): an older Serve passes a client's own copy through |
| `KANBAN_BIND` | `0.0.0.0` | the address the listener binds. Behind `tailscale serve` on a native install, bind `127.0.0.1`: on a public bind anyone who reaches the port could send the `Tailscale-User-Login` header |
| `KANBAN_TAILNET_PORT` | `8081` | the listener's port |
| `KANBAN_REPO`, `KANBAN_DB` | `/repo`, `/data/kanban.sqlite3` | the board's clone of the vault and its SQLite cache |
| `KANBAN_REPO_SUBDIR` | repo root | the folder of the repo that holds the notes, when it is not the root (the board reads and writes only there, plus `.board/`); with `KANBAN_REPO_SPARSE`, name the same folder |
| `KANBAN_EXPORT_IDLE`, `KANBAN_EXPORT_MAX` | `120`, `900` | the board's edits are committed after this many seconds idle, or at most this long after the first one |
| `KANBAN_PULL_SECONDS`, `KANBAN_VERIFY_SECONDS` | `60`, `3600` | how often it pulls the repository, and how often it checks its cache against a fresh scan of the notes |
| `KANBAN_WIP_LIMITS` | — | the weekly review's per-area WIP limits, `ops=4,docs=5` (other areas get 3) |
| `KANBAN_SKIP_COMMITS`, `KANBAN_CALENDAR_SKIP_COMMITS` | — | commit subjects to leave out, comma-separated prefixes (case-insensitive), on top of the board's own `board: ` and `Merge ` commits: the first from the calendar, roundups and kits (e.g. `nightly backup`), the second from the calendar and roundups only (commits the events and Log tables already cover) |
| `KANBAN_ARCHIVE` | `none` | `none`: the link checker still visits the links in cards' notes to see if they are alive, but never contacts the Wayback Machine (snapshots already recorded still show). `wayback` (exactly this word; anything else counts as `none` and logs a warning): it also asks the Wayback Machine for a snapshot of each link and saves one (this sends the URL to archive.org) |
| `KANBAN_REPO_REFERENCE`, `KANBAN_REPO_SPARSE` | — | Machiya stack mode: borrow the stack's vault mirror's objects, and check out only `notes,.board` (your `KANBAN_REPO_SUBDIR` plus `.board`; see `CLAUDE.md`) |
| `KANBAN_BOARD_URL` | — | this board's own address, for absolute links in writing kits. With an identity file it is also the one origin the sign-in, sign-out and preference checks accept (unset: an https page naming the request's own `Host`), and an `http://` address takes `Secure` off the session cookie |
| `KANBAN_NIWA_URL`, `KANBAN_KURA_URL` | — | the sister rooms (Niwa: the garden links and the `/garden/` redirect; Kura: "View in Kura"). Unset = those links are off |
| `KANBAN_OBSIDIAN_VAULT` | — | the Obsidian vault's name for "Open in Obsidian" links (`obsidian://open?vault=my-vault`). Unset = no such links |
| `KANBAN_GIT_AUTHOR_NAME`, `KANBAN_GIT_AUTHOR_EMAIL` | `konbini`, `konbini@localhost` | who the board's commits to the vault are by |
| `KANBAN_LINKS_USER_AGENT` | `konbini-links/1` | the link checker's User-Agent (add a contact URL for the sites it checks) |
| `KANBAN_LINKS_SKIP_HOSTS` | — | more hosts the link checker never visits, comma-separated (loopback, `192.168.*`, `10.*`, `100.*`, `*.ts.net` and `archive.org` are always skipped) |
| `KANBAN_HISTER_URL`, `KANBAN_HISTER_PUBLIC`, `KANBAN_COLD_MAP` | — | optional: Hister (private copies of links, "pages I've read") and a cold-archive URL map |
| `KANBAN_HISTER_SAVE` | off | `1`, `on` or `true`: the link checker also indexes live links Hister doesn't have yet (needs `KANBAN_HISTER_URL`). Off: it only shows Hister's existing copy (a read-only lookup); saving pages is Shiori's job |
| `KANBAN_HISTER_TOKEN_FILE` | — | path to a file holding your Hister token (one line; mount it read-only, owner-only): sent as `X-Access-Token` on every call Konbini makes to Hister, and to the `hister` CLI as `HISTER__APP__ACCESS_TOKEN` in its environment (never on its command line). Read at each call, so a rotated token needs no restart. It is never logged, shown on a page or returned by the API; a missing or empty file sends nothing and shows as Hister's error on `/api/status`. Unset: nothing is sent (needs `KANBAN_HISTER_URL`) |
| `KANBAN_BLOG`, `KANBAN_BLOG_URL`, `KANBAN_BLOG_PERMALINK` | `/blog`, —, `/{year}/{slug}/` | optional: a Jekyll blog checkout (posts in `_posts/` as `YYYY-MM-DD-slug.md` or `.html`, optional `tag/<tag>.md` pages), its address, and the path of a post's page under that address (`{year}` and `{slug}`), for the writing kits' "already written?" links |
| `KANBAN_LIVESYNC_STATUS` | — | optional: a JSON file written by whatever syncs phone edits into the repository (an Obsidian LiveSync bridge), re-read every 10 s and shown in the board's alerts. Keys the board reads: `daemon` (`"running"` or an alert), `last_cycle_ts` (unix seconds, alert if older than 5 minutes) and `last_cycle` (its text), `git_ok_ts` (unix seconds of the last good push, alert after 30 minutes) and `git_ok_at` (its text), `held_deletes` and `unresolved` (lists, alerted by length). Unset or missing = no alerts |
| `KANBAN_REPOS` | `/repos` | optional: read-only checkouts of project repos, for the writing kits' commit lists |
| `TZ` | `UTC` | the board's days (calendar, roundups, the review's week) |
| `MACHIYA_ROOMS` | — | the Rooms switcher, `shiori=https://…,konbini=…,niwa=…,kura=…,hister=…,searxng=…,machiya=…` (`machiya` is the stack's front door: the menu's "Machiya · home" row and the footer link; the stack sets it) |
| `MACHIYA_SOURCE_URL` | — | where this room's source code is published; when set, the footer and About link to it (AGPL section 13: people who use a service over a network are offered its source). A plain http(s) address |
| `MACHIYA_COOKIE_DOMAIN` | — | share the theme and text-size cookies across rooms on one domain, e.g. `example.net` |

Every setting is in this table: the `KANBAN_*` ones, `TZ` and the `MACHIYA_*` ones.

### Sign-in, pairing and preferences

Sign-in and pairing exist only with `MACHIYA_IDENTITY_FILE` (vaultkit's `signin`); without the file they answer
404. Preferences are served in every mode: without the file they are the person the old gate let in (the Tailscale
login, or open mode's owner), so theme and text size follow them to another device.

| Route | Gate | What it does |
|---|---|---|
| `GET /signin`, `POST /signin` | before (needs `KANBAN_SIGNIN=1`, else 404) | the sign-in form, and its same-origin post: a session cookie and a 303 to `next` (a local path) |
| `POST /signout` | before | same-origin only: clears the session cookie |
| `POST /api/pair` | before | Shiori's device pairing: `{"code", "device"}` (a code from `python3 -m vaultkit.identity pair <name>`, run in `app/`) gives `{"token", "principal"}`, a device token for `Authorization: Bearer`. Works with or without `KANBAN_SIGNIN` |
| `GET /api/prefs`, `PUT /api/prefs` | after (`konbini` `read`, or the old gate) | the caller's own preferences, `{"prefs": {key: value}}`; a PUT merges (`null` removes) |

`KANBAN_AUTH=open`'s `Host` rule comes first for all of them. They follow vaultkit's rules, not the board's `/api`
write rule: pairing carries no cookie (the code is the proof), so it needs neither `X-Agent` nor an `Origin`; a
`PUT /api/prefs` made with a token needs neither either, and one made with a session cookie, a Tailscale or proxy
login or in open mode must come from the board's own page (`Origin`, else `Referer`; `X-Agent` doesn't excuse it):
`KANBAN_BOARD_URL`'s origin, else an https page naming the request's own `Host`, or in open mode without an identity
file the request's own `Host` over http too (it already passed the `Host` rule).
Preferences are kept per principal in `prefs.sqlite3` next to `KANBAN_DB` (mode 0600; not the board's cache, so a
`rebuild` keeps them). With an identity file the header shows who is signed in, and Settings has an Account
section (with Sign Out for a sign-in session).

## Vault layout

Konbini expects a git repository of Markdown notes (the repository root, or one folder of it: set `KANBAN_REPO_SUBDIR`). A card is a note whose `status:` is a board column. New cards are written to `Projects/<Title>.md` with the tags `type/idea` and `area/projects` plus one `area/<lane>` tag: the lane is the first area tag other than `area/projects`. The calendar, roundups and writing kits also read, from any note, dated rows of a table (`| 2026-01-15 | milestone | Shipped | details |`: a date, a category, a change, then anything); a card's `## Log` table gives its milestones, and tables in `Systems/<host>.md` notes give machine changes (without those notes the pages just have fewer rows). A card's note may contain a generated block between `<!-- project-sync:start -->` and `<!-- project-sync:end -->` whose bullets `- YYYY-MM-DD: commit subject` the kit uses as the repository's recent commits when it cannot fetch them. Writing kits can map a card's topics and area onto your blog's tags and categories through an optional `.board/kit.json` in the repository (`tag_synonyms`, `area_category`, `default_category`, `ignore_tags`, `ignore_categories`); without it the blog's own tags and categories drive the kit. Frontmatter fields are described in `docs/frontmatter.md` of the [Machiya repository](https://github.com/machiya-kobo/machiya).

## The pm command line

`tools/pm` is a one-file command line for a board (Python 3, standard library only; copy it onto your `PATH` or run it in place). It talks to Konbini's HTTP API at `KANBAN_URL` (default `http://127.0.0.1:8081`) and sends `X-Agent` (`pm@<host>`, or `KANBAN_AGENT`) so a card's history says who changed it. For a board on `KANBAN_AUTH=hister`, `KANBAN_TOKEN_FILE` names a file holding the owner's Hister token (get it from your password store; never put it in an argument or a note); pm sends it to the board and to Niwa (the garden suggestions) only, as `Authorization: Bearer`, over https (plain http only to this machine), and follows no redirect while it does. A room token (`mht_…`, minted for Konbini and Niwa by the hister-login helper) is what it should hold; an address without a scheme is https.

```sh
pm ls --area tools            # cards (also --board, --machine, --topic, --tag, --json)
pm show <slug>                # one card
pm new "Title" --area tools --summary "one line"
pm move <slug> wip            # backlog | ready | wip | blocked | done | archived
pm next <slug> "the next concrete action"
pm block <slug> "waiting on a part"      # moves to blocked with a reason
pm log <slug> "a note for the card's history"
pm tag <slug> +topic/a -topic/b          # existing tags only
pm dep <slug> +other-card -old-card      # dependsOn; with no changes it lists them
pm stream <slug> "Release 1.0"           # also: pm goal, pm due; "-" clears
pm claim <slug>                          # "an agent is working on this" badge, 15 minutes
pm review                                # the weekly review (--json for the raw data)
pm roundup week                          # what got done: day | week | month | year
pm kit <slug>                            # the writing kit as Markdown
pm post <slug> drafting <url>            # track the blog post (none, idea, outlined, drafting, published, skipped)
pm health                                # the board's /api/health
```

The area in `pm new` must already exist: the board refuses new `area/*` tags from the command line, so create a first lane in the web form. `pm tag` takes existing tags only. `pm suggest <note>` asks Niwa to consider a note for the garden; it needs `NIWA_URL` (Niwa's address) and is off without it. If the board answers 405 (an endpoint an older board lacks), `pm` says so. The `X-Agent` label (and with it your host name) is recorded in the card's history in the repository's `.board/events`. The settings that start with `KANBAN_` keep the prefix from Konbini's earlier name.

Layout and rules for working on the code: see `CLAUDE.md`; changes by release: [`app/CHANGELOG.md`](app/CHANGELOG.md).

## Licence

Konbini is free software: GNU Affero General Public License, version 3 or (at your option) any later version.
See `LICENSE`. Third-party software it ships (SortableJS, Mermaid, the Hister CLI in the image) is listed with
its licences in `THIRD_PARTY_NOTICES`.
`app/urlnorm.py` (the URL normalisation rule, identical to the copy in Niwa) is the project's own code, under the same licence.

Copyright (C) 2026 Micheal Waltz and Machiya contributors.
