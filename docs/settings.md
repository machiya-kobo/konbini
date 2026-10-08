# Settings

Konbini reads its settings from the environment, or from a file with `KANBAN_ENV_FILE`. Every setting is here: the
`KANBAN_*` ones (the prefix is from Konbini's earlier name), `TZ` and the shared `MACHIYA_*` ones. Each default is
safe for a public install.

[Access](#access) · [Hister sign-in](#hister-sign-in) · [The vault and git](#the-vault-and-git) · [Pages](#pages) · [Writing kits](#writing-kits) · [Links and Hister](#links-and-hister) · [Other apps](#other-apps) · [Running it](#running-it)

## Access

Who may use the board and how it listens. [Who can use it](access.md) puts these together.

| Setting | Default | |
|---|---|---|
| `KANBAN_AUTH` | `tailscale` | `tailscale`: every page and write needs a `Tailscale-User-Login` in `KANBAN_TAILNET_USERS` (or, with an identity file, a principal the file names). `open`: no identity check (a startup warning), for localhost or a trusted LAN only; the identity header is ignored and writes are logged as `local`. `header` (only with `MACHIYA_IDENTITY_FILE`): a trusted proxy's login header (`KANBAN_AUTH_HEADER`). `hister`: Hister's users are the sign-in (see [Hister sign-in](#hister-sign-in); never with an identity file). Either way, form posts must be same-origin, and an API write from outside the board's pages must send `X-Agent` and no cross-site `Origin` or `Referer` (CSRF; 403 otherwise). Any other value refuses to start |
| `KANBAN_TAILNET_USERS` | — | allowed `Tailscale-User-Login`s, comma-separated; unset = nobody (with `KANBAN_AUTH=tailscale`). Not used with an identity file |
| `KANBAN_ALLOWED_HOSTS` | — | with `KANBAN_AUTH=open`: the host names the board answers to, comma-separated (case, port and a trailing dot don't matter), on top of IP addresses, `localhost` and `KANBAN_BOARD_URL`'s host. Any other `Host` gets 403, so a web page can't reach the board by pointing its own name at your machine (DNS rebinding). Ignored with `tailscale` |
| `KANBAN_BIND` | `0.0.0.0` | the address the listener binds. Behind `tailscale serve` on a native install, bind `127.0.0.1`: on a public bind anyone who reaches the port could send the `Tailscale-User-Login` header |
| `KANBAN_TAILNET_PORT` | `8081` | the listener's port |
| `KANBAN_BOARD_URL` | — | this board's own address, for absolute links in writing kits. With an identity file it is also the one origin the sign-in, sign-out and preference checks accept (unset: an https page naming the request's own `Host`), and an `http://` address takes `Secure` off the session cookie |
| `MACHIYA_IDENTITY_FILE` | — | Machiya's identity file (vaultkit's `identity`; [Machiya's `docs/identity.md`](https://github.com/machiya-kobo/machiya/blob/main/docs/identity.md)): people, agents and services with grants. Set, it replaces `KANBAN_TAILNET_USERS` and the `X-Agent` test for owner powers: every page and read API needs the `konbini` `read` grant, every change (card edits, comments, claims, the board's forms) `write`, and new `area/*` lanes and new tags `areas`. No proof or a bad one gets 401, a missing grant 403; an event's actor is the principal (`X-Agent` stays a label). With `KANBAN_AUTH=open` a request without a token is the owner. Mount the file's directory read-only (not the file: the CLI replaces it, and a file mount keeps the old one) |
| `KANBAN_SIGNIN` | — | `1`, with an identity file: the built-in sign-in (a person's name and password from the file, a `machiya_session` cookie; see [Sign-in, pairing and preferences](access.md#sign-in-pairing-and-preferences)). A browser without a session then gets a 401 page linking to `/signin?next=<the page>`. Behind an https proxy leave `KANBAN_BOARD_URL` https or unset; on plain http set it to the board's `http://` address, or every sign-in is refused (403) |
| `KANBAN_AUTH_HEADER` | — | with an identity file and `KANBAN_AUTH=header`: the trusted proxy's login header (`Remote-User`, …), matched against the principals' `proxy` logins |
| `KANBAN_BIND_BEHIND_PROXY` | — | `1`: a proxy (the Tailscale sidecar) is the only way in, so a header-trusting mode may bind a non-loopback address. It applies with an identity file (`KANBAN_AUTH=tailscale` or `header`) and with `KANBAN_AUTH=hister` (its `tailscale` fallback); in those modes, without it, the board refuses to start on anything but a loopback address. It isn't enough on its own: see `KANBAN_TRUSTED_PROXIES` |
| `KANBAN_TRUSTED_PROXIES` | — | addresses or CIDRs (comma-separated, e.g. `10.210.4.2/32`) of the proxies in front of the board. Set, an identity header (`Tailscale-User-Login` and Tailscale's others, `Remote-User`, `KANBAN_AUTH_HEADER`) counts only on a connection from one of them; from any other peer it is dropped, so the request is anonymous. Unset: headers count from any peer, which is only safe on a loopback bind behind `tailscale serve`. A mode that believes the header (`KANBAN_AUTH=tailscale` or `header`, or `hister` with its `tailscale` fallback) on any other bind refuses to start without it; `0.0.0.0/0` says every peer is trusted, and `KANBAN_AUTH_FALLBACK=none` removes the need in hister mode |
| `KANBAN_ACCEPT_APP_CAPS` | — | `1`: read Tailscale's forwarded app capability (`Tailscale-App-Capabilities`) for tagged nodes. Only where Serve forwards it (`--accept-app-caps`, Tailscale v1.92+): an older Serve passes a client's own copy through |

## Hister sign-in

With `KANBAN_AUTH=hister`, Hister's users sign in through Machiya's hister-login helper.

| Setting | Default | |
|---|---|---|
| `KANBAN_AUTH_SIGNIN_URL` | — | with `KANBAN_AUTH=hister` (required): the hister-login helper's public sign-in page, where a signed-out page is sent (it comes back to the page it left; at most one trip per 30 s per browser, then a page with a link). With `KANBAN_HISTER_USERS`, `KANBAN_BOARD_URL` and `KANBAN_AUTH_URL` this is the whole of [Machiya's Hister sign-in](https://github.com/machiya-kobo/machiya/blob/main/docs/identity.md#hister-sign-in-authhister) |
| `KANBAN_AUTH_URL` | — | with `KANBAN_AUTH=hister`: the helper's internal address (`http://hister-login:8081`), which the board asks who is calling. Unset: Konbini runs on the tailnet login alone, with a start-up warning (with `KANBAN_AUTH_FALLBACK=none` it refuses to start) |
| `KANBAN_HISTER_USERS` | — | with `KANBAN_AUTH=hister` (required): the Hister usernames admitted, comma-separated, never `*`. Another Hister account is refused (403), never passed on to the fallback |
| `KANBAN_AUTH_FALLBACK` | `tailscale` | with `KANBAN_AUTH=hister`: what happens when sign-in is unavailable (the helper or Hister unreachable, a 5xx, or Hister's user handling off). `tailscale`: the `Tailscale-User-Login`s in `KANBAN_TAILNET_USERS` are admitted as the owner, with a banner; `none`: 503. Someone who is simply signed out is never let in this way. `KANBAN_BOARD_URL` is required in this mode (the way back). `/api/health`, `/api/status` and `/api/changelog` answer without a sign-in, so probes and the status page keep working (the owner sees the full health). Sign out is `POST /signout` (same-origin). A headless client (`pm`, a script, the MCP) sends a room token the helper minted for Konbini as `Authorization: Bearer mht_…` (`pm`: `KANBAN_TOKEN_FILE`), or the owner's Hister token as `X-Access-Token`. Browsers get their own host-only cookie per room (`__Host-machiya_sso_konbini`, a room session the helper hands over once through `/machiya/callback`) |
| `KANBAN_AUTH_ACCEPT_ORIGINS` | — | with `KANBAN_AUTH=hister`: other origins (`https://host[:port]`, comma-separated, nothing after the host) whose room sessions this board also accepts: the hosted Shiori pages, whose own proxy passes their room cookie on. Every check the board makes names its own origin first, then these |
| `MACHIYA_SSO_COOKIE` | `machiya_sso` | with `KANBAN_AUTH=hister`: the name of the Hister sign-in cookie; set the same value in the hister-login helper and every room. Only for a second stack under the same cookie domain (a dev stack, say). Letters, digits, `_` and `-` |

## The vault and git

Where the notes are, and how Konbini commits, pulls and checks them.

| Setting | Default | |
|---|---|---|
| `KANBAN_REPO`, `KANBAN_DB` | `/repo`, `/data/kanban.sqlite3` | the board's clone of the vault and its SQLite cache |
| `KANBAN_REPO_SUBDIR` | repo root | the folder of the repo that holds the notes, when it is not the root (the board reads and writes only there, plus `.board/`); with `KANBAN_REPO_SPARSE`, name the same folder |
| `KANBAN_EXPORT_IDLE`, `KANBAN_EXPORT_MAX` | `120`, `900` | the board's edits are committed after this many seconds idle, or at most this long after the first one |
| `KANBAN_PULL_SECONDS`, `KANBAN_VERIFY_SECONDS` | `60`, `3600` | how often it pulls the repository, and how often it checks its cache against a fresh scan of the notes |
| `KANBAN_GIT_AUTHOR_NAME`, `KANBAN_GIT_AUTHOR_EMAIL` | `konbini`, `konbini@localhost` | who the board's commits to the vault are by |
| `KANBAN_REPO_REFERENCE`, `KANBAN_REPO_SPARSE` | — | Machiya stack mode: borrow the stack's vault mirror's objects, and check out only `notes,.board` (your `KANBAN_REPO_SUBDIR` plus `.board`; see `CLAUDE.md`) |
| `KANBAN_LIVESYNC_STATUS` | — | optional: a JSON file written by whatever syncs phone edits into the repository (an Obsidian LiveSync bridge), re-read every 10 s and shown in the board's alerts. Keys the board reads: `daemon` (`"running"` or an alert), `last_cycle_ts` (unix seconds, alert if older than 5 minutes) and `last_cycle` (its text), `git_ok_ts` (unix seconds of the last good push, alert after 30 minutes) and `git_ok_at` (its text), `held_deletes` and `unresolved` (lists, alerted by length). Unset or missing = no alerts |

## Pages

The review, the calendar and roundups.

| Setting | Default | |
|---|---|---|
| `KANBAN_WIP_LIMITS` | — | the weekly review's per-area WIP limits, `ops=4,docs=5` (other areas get 3) |
| `KANBAN_SKIP_COMMITS`, `KANBAN_CALENDAR_SKIP_COMMITS` | — | commit subjects to leave out, comma-separated prefixes (case-insensitive), on top of the board's own `board: ` and `Merge ` commits: the first from the calendar, roundups and kits (e.g. `nightly backup`), the second from the calendar and roundups only (commits the events and Log tables already cover) |
| `TZ` | `UTC` | the board's days (calendar, roundups, the review's week) |

## Writing kits

Where a kit finds your blog and your code.

| Setting | Default | |
|---|---|---|
| `KANBAN_BLOG`, `KANBAN_BLOG_URL`, `KANBAN_BLOG_PERMALINK` | `/blog`, —, `/{year}/{slug}/` | optional: a Jekyll blog checkout (posts in `_posts/` as `YYYY-MM-DD-slug.md` or `.html`, optional `tag/<tag>.md` pages), its address, and the path of a post's page under that address (`{year}` and `{slug}`), for the writing kits' "already written?" links |
| `KANBAN_REPOS` | `/repos` | optional: read-only checkouts of project repos, for the writing kits' commit lists |

## Links and Hister

The link checker for the links in your cards' notes, and an optional Hister for private copies.

| Setting | Default | |
|---|---|---|
| `KANBAN_ARCHIVE` | `none` | `none`: the link checker still visits the links in cards' notes to see if they are alive, but never contacts the Wayback Machine (snapshots already recorded still show). `wayback` (exactly this word; anything else counts as `none` and logs a warning): it also asks the Wayback Machine for a snapshot of each link and saves one (this sends the URL to archive.org) |
| `KANBAN_LINKS_USER_AGENT` | `konbini-links/1` | the link checker's User-Agent (add a contact URL for the sites it checks) |
| `KANBAN_LINKS_SKIP_HOSTS` | — | more hosts the link checker never visits, comma-separated (loopback, `192.168.*`, `10.*`, `100.*`, `*.ts.net` and `archive.org` are always skipped) |
| `KANBAN_HISTER_URL`, `KANBAN_HISTER_PUBLIC`, `KANBAN_COLD_MAP` | — | optional: Hister (private copies of links, "pages I've read") and a cold-archive URL map |
| `KANBAN_HISTER_SAVE` | off | `1`, `on` or `true`: the link checker also indexes live links Hister doesn't have yet (needs `KANBAN_HISTER_URL`). Off: it only shows Hister's existing copy (a read-only lookup); saving pages is Shiori's job |
| `KANBAN_HISTER_TOKEN_FILE` | — | path to a file holding your Hister token (one line; mount it read-only, owner-only): sent as `X-Access-Token` on every call Konbini makes to Hister, and to the `hister` CLI as `HISTER__APP__ACCESS_TOKEN` in its environment (never on its command line). Read at each call, so a rotated token needs no restart. It is never logged, shown on a page or returned by the API; a missing or empty file sends nothing and shows as Hister's error on `/api/status`. Unset: nothing is sent (needs `KANBAN_HISTER_URL`) |

## Other apps

Links to Machiya's other apps and to Obsidian. Each is off while unset.

| Setting | Default | |
|---|---|---|
| `KANBAN_NIWA_URL`, `KANBAN_KURA_URL` | — | the sister rooms (Niwa: the garden links and the `/garden/` redirect; Kura: "View in Kura"). Unset = those links are off |
| `KANBAN_OBSIDIAN_VAULT` | — | the Obsidian vault's name for "Open in Obsidian" links (`obsidian://open?vault=my-vault`). Unset = no such links |
| `MACHIYA_ROOMS` | — | the Rooms switcher, `shiori=https://…,konbini=…,niwa=…,kura=…,hister=…,searxng=…,machiya=…` (`machiya` is the stack's front door: the menu's "Machiya · home" row and the footer link; the stack sets it) |
| `MACHIYA_SOURCE_URL` | — | where this room's source code is published; when set, the footer and About link to it (AGPL section 13: people who use a service over a network are offered its source). A plain http(s) address |
| `MACHIYA_COOKIE_DOMAIN` | — | share the theme and text-size cookies across rooms on one domain, e.g. `example.net` |

## Running it

| Setting | Default | |
|---|---|---|
| `KANBAN_ENV_FILE` (or `--env-file PATH`) | — | native installs (e.g. BSD rc.d): read these settings from a file of `KEY=VALUE` lines first; the real environment wins. A missing or bad file stops start-up, naming the file and line |
