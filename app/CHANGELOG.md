# Changelog

Konbini follows [SemVer](https://semver.org). Before 1.0, a new feature, a changed default or setting, or a changed
API field is a minor bump; a fix, wording or internal change is a patch.

## 0.18.2

- Hovering a pill or link chip thickens its outline instead of filling it (vaultkit 0.26.3: the light fill pulled some themes' text under 4.5:1).
- The README and install guide are tighter: one link row (Machiya, Quickstart, Install, Settings, then Access, Vault layout, pm, License), the Quickstart pins `markdown` 3.11+, "More ways to run it" and "Docs" are gone (the install guide and the link row cover them), and the License section has the wording the Machiya apps share.
- The image runs as `USER 1000:1000` by itself, not only when the compose file says so.

## 0.18.1

- The room's icons (`/static/icons/*` and `/favicon.ico`) answer before the gate in every access mode, so a browser has its tab icon on the sign-in page and before anyone has signed in. They hold no board data.
- Hister calls (which carry the access token) no longer follow a redirect: it is an error, so the token goes to Hister and nowhere else.
- The board's log lines no longer include a request's query string (search terms and filters).
- A test (`tests/test_private_names.py`, from the Machiya repository) keeps private host, account and people's names out of the repository; it reads its list from outside the repository and skips without it.

## 0.18.0

Shiori's look, shared with every Machiya app (the style guide, vaultkit 0.26.2):
- **Filter pills.** Group By (Area, Stream (Project), Family) and Area are pills above the board, with counts, always visible (also on a phone); the current one is filled. The phone's column tabs, the Plan nav, the review's section jumps, Posts' Show row, the Timeline's range and Group By, and the calendar's and roundup's month and period rows are the same pills. Topic, machine, claimed, effort and stream stay selects in the filter form: they have too many values for a row.
- **Chips.** Priorities, statuses, due dates, claims and counts are the shared state chips, outlined in their colour; a stream, a goal, an active filter, and the card page's Kura, Obsidian and Niwa links are link chips; topics are neutral tags.
- **Icons.** The browser tab uses `konbini-small.svg` (the icon with the fine detail dropped, so it reads at 16 px) and `konbini.ico` (16, 32 and 48 px from it); `/favicon.ico` answers with it too. The home-screen, manifest and header icons are the full drawing, as before.

## 0.17.0

- **`KANBAN_TRUSTED_PROXIES`** (addresses or CIDRs, comma-separated): an identity header (`Tailscale-User-Login` and Tailscale's others, `Remote-User`, `KANBAN_AUTH_HEADER`) counts only on a connection from one of them. From any other peer it is dropped before the board reads it, so the request is anonymous. Without it a peer on the same network as the board could claim to be anyone.
- **Breaking:** a mode that believes the header (`KANBAN_AUTH=tailscale` or `header`, or `hister` with its `tailscale` fallback) on a bind that isn't loopback now refuses to start without `KANBAN_TRUSTED_PROXIES`. Bind `127.0.0.1` behind `tailscale serve`, name the proxy (a sidecar's address, like `10.210.4.2/32`), or set `KANBAN_AUTH_FALLBACK=none` in hister mode. `0.0.0.0/0` trusts every peer, which is what an unset setting meant before.

## 0.16.0

Adding, editing and closing cards:
- **Descriptions.** A card has a description: the text under its note's title, up to the next heading. The card page shows it, and the New Card form, the card form, the API (`description`) and `pm` write it. Kits use it as the overview. This is the one part of a note's body the board writes (it can't contain headings, and everything below it is left alone); if you and the board both change it between two pulls, the board keeps yours.
- **One card page.** The read-only table and the form that repeated it are one page. Title, Summary, Description, Stream, Area, Priority, Next and Due are up front; Waiting on, Depends on, Goal (and Post and Post URL, once a card is finished) sit under More. "Add note" is Comment. Area changes a card's swimlane to one that exists.
- **Closing out.** Archive and Won't do (with an optional reason) are on the card page and in the phone sheet, offline too. A closed card shows how it was closed and can be moved back to a column. Cards closed as won't do stay out of Posts. `pm archive` and `pm drop`.
- **New Card details.** Summary, Stream, Priority and Description when you add a card, right on the board.
- **Projects.** A stream is a project, and the pages say so: Group By offers Stream (Project) in Settings and the filter bar, and a stream's chip links to its page.
- API, all additive: `GET /api/cards/<slug>` has `description`; `PATCH` takes `description`, `area`, and `outcome: "wontdo"` with `reason` when archiving; `POST /api/cards` takes `description` and `stream`. `pm describe`, `pm area` and `--description` and `--stream` on `pm new`.
- Fixes: a multi-line field no longer looks "changed since you opened this page" when a browser posts its line breaks as CRLF.

## 0.15.5

- Machine change logs kept as monthly notes (`Systems/Change Logs/<host> YYYY-MM.md`, with `host:` in the frontmatter) are named after the machine, not the month note, in roundups, the calendar, the digest (one entry per host per day) and a writing kit's machine changes. The older one-note-per-host tables work as before, and a host note's list of links to its months adds nothing.
- A writing kit no longer lists a whole machine's change log for a card whose repository is named after that machine.

## 0.15.4

- vaultkit 0.25.2: code in a writing kit and the search page's field use the readable text colour for raised backgrounds, from the shared stylesheet (Konbini's own override is gone).

## 0.15.3

- Readable in every theme: all text on the board's pages now has at least 4.5:1 contrast in all ten palettes, light and dark (vaultkit 0.25's panel shades on lanes, chips, forms, the action sheet and the calendar). The Backlog column, P3 and "stale" use the muted text colour; stream, goal and dependency chips keep their colour in the text and border; finished cards' titles and out-of-month calendar days are no longer faded.
- About says "License".

## 0.15.2

- vaultkit 0.24: the footer's status line, the phone tab bar's labels and the Settings groups' text are easier to read (at least 4.5:1 contrast in every theme and mode).

## 0.15.1

- A note or a new card sent from the offline queue carries its own id (`client_id`), and the board keeps it with the event: a retry after an answer that got lost (the change reached the board, the phone never heard back) no longer adds the note or the card twice. The card form, `POST /api/cards` and `POST /api/cards/<slug>/events` accept the optional `client_id`; the event it makes carries it.
- A name clash on a new card made offline is shown instead of being taken for your own card.
- A send from the queue that never finishes gives up after 20 seconds and is tried again later, instead of holding up the rest.
- The queue also sends as soon as the board answers its regular check, in case the browser misses going online.
- A new card in the projects area no longer gets its `area/projects` tag twice.

## 0.15.0

Changes made offline wait on the device and are sent when the board can be reached again, in the installed app and the browser:
- Moves (the sheet, the keys, drag and drop, the column buttons), field edits, notes and new cards that can't reach the board are kept on this device (IndexedDB), shown on the page at once and marked "waiting"; a badge says how many wait.
- They are sent in order on the next load, when the browser goes online, when the tab comes back, and from the service worker where Background Sync exists. A new card shows as a stand-in until the board has it; changes to it follow under its real name.
- Each carries what it was based on, so a card somebody changed meanwhile isn't overwritten: the badge's sheet shows yours and the board's, with Keep Mine or Use the Board's. A deleted card or a refused change is shown until dismissed. A signed-out browser keeps them until you sign in again. Nothing about your sign-in is stored with them.
- Tag changes still need the board (a new tag asks first).
- The card form now refuses a column move based on a column the card has left (`o_board`), like its other fields.
- Fix: pressing Enter in a card's inline Next field saved it twice.

## 0.14.0

Settings in the same order as every Machiya app (vaultkit 0.23):
- Appearance first (Theme, Mode, Text Size, with Use This Device's Size right under it), then Board, Rooms, Account, About.
- Offline Copies moved into Board (it was the only row left in This Device, which is gone); it stays on this device. Group By and Done Cards are unchanged.
- No setting, key or cookie changed; only placement and names (Shared is now Appearance, Appearance is now Mode).
- vaultkit 0.23 also shortens the shared Settings, offline and About copy.

## 0.13.2

- Shorter page copy: the Settings notes (Board, This Device, Account), the Posts, Capture, Archived and Dependencies intros, the Streams and Goals empty states, and a few tooltips say only what you need. No change in behaviour. The `/share?url=…&title=…` link for an iOS Shortcut is in the README now.

## 0.13.1

- Pull to refresh in the installed app moves the page content with your finger (it springs back when let go early, holds with a spinner while it reloads); the header and tab bar stay put, and dragging a card still just drags the card (vaultkit 0.22.1).

## 0.13.0

vaultkit 0.22 (the sweep's shared fixes):

- Sign-in with `KANBAN_AUTH=hister` keeps a cookie of its own for this board: `__Host-machiya_sso_konbini`, host-only, set by the board from a one-time code the helper sends back to `/machiya/callback` (so no other site on the domain can plant or read it, and a session copied to another room is refused). Headless callers (`pm`, scripts) send a room token (`Authorization: Bearer mht_…`) that opens only the rooms it names. `KANBAN_AUTH_ACCEPT_ORIGINS` lists other origins whose room sessions this board also accepts (the hosted Shiori pages).
- `pm`: `KANBAN_TOKEN_FILE` holds a room token, sent to Konbini and to Niwa's API (never to another host, never over plain http except to this machine, no redirect followed while it is sent).
- No script from a note can run through the shared code any more (symlinks are skipped and never written through; notes are written only through `safe_path`); every answer carries `nosniff`, framing and referrer rules; the link checker vets the address of each connection when it opens, redirects included.
- Needs Python-Markdown 3.11 or later (older ones can be driven out of memory by one note). The image pins `markdown==3.11` and `pyyaml==6.0.3`.
- Menus close on the back button and pull-to-refresh works in the installed app.

## 0.12.1

Fixes from the stack's security sweep (October 2026):

- A link such as `/garden/x%0D%0ASet-Cookie:…` could inject a response header (a cookie planted for the whole tailnet domain): a control character in an address is now a 400, no response header can carry one, and the garden redirect encodes its path.
- One card's text could stop the board's git export for good: a newline in a title or summary could write a bare `=======` line. Titles and summaries are one line of plain text now, a card always gets a usable file name, and a note that still has a conflict marker is held out of a commit while everything else is exported.
- The card form saves only the fields you changed and refuses one that somebody else changed meanwhile (it used to write back every field it was drawn with, undoing an agent's edits); the note is written after the update was accepted, and only on a card that exists. Drag and drop leaves a card alone that was moved meanwhile.
- Bad input (a non-numeric `limit`, years like 9999, a list of the wrong type, a title over 255 bytes, `minutes: 1e999`) is an answer, and anything unexpected is a JSON 500, instead of a dropped connection.
- The link checker only calls public addresses (it resolves every name and checks each redirect, IPv6 included), and the private network is never reached from a link in a note.
- SVG answers are sandboxed and every answer carries `nosniff`; `repo:` and `post_url:` are links only when they are http(s).
- A merge a replay had to drop is shown on the board, comments are written under the writer lock.
- `pm` (and the dotfiles wrapper) send the Hister token only to the board, never over plain http (except to this machine), never follow a redirect while sending it, and default to https.

## 0.12.0

- Settings follow the signed-in person (vaultkit 0.21): with `KANBAN_AUTH=hister` and the helper, Theme, Appearance, Text Size, which apps the Rooms menu shows, and Konbini's own Group By and Done Cards are kept in your account and follow you to every app and device. A fresh browser is drawn in your theme from its first page. `/settings` starts with a Shared section (where they are kept now), then Board, This Device (Use This Device's Size, Offline Copies), Account and About.
- `/api/prefs` answers `{"v", "rev", "prefs", "updated"}` and accepts only the schema's keys (docs/contracts/prefs.md).
- OpenBSD starts: vaultkit no longer needs `hashlib.scrypt` at import (only the built-in password sign-in does).

## 0.11.12

- Hister queries leave out code documents (`-metadata.source:code`, from the coming code search): a repo, README or issue is never shown as a page you read or a saved copy.

## 0.11.11

- `MACHIYA_SSO_COOKIE` names the Hister sign-in cookie (default `machiya_sso`, unchanged), so a second stack on the same domain (the dev stack) can use its own (vaultkit 0.20.0).

## 0.11.10

- The Rooms menu's Machiya row reads "Machiya · home": the stack's front door; its status page moved to /status (vaultkit 0.19.1).

## 0.11.9

- `KANBAN_AUTH=hister`: Hister's sign-in (through the hister-login helper) as the board's gate; when sign-in is unavailable the owner's tailnet login still gets in, with a banner; the owner's events keep their actor; `pm` sends `KANBAN_TOKEN_FILE` as a Bearer token (vaultkit 0.19.0). Off by default; `tailscale` is unchanged.

## 0.11.8

- `KANBAN_HISTER_TOKEN_FILE`: the owner's Hister token, sent as `X-Access-Token` on every call to Hister (and to the `hister` command's environment, never its arguments), for the coming Hister sign-in. Unset sends nothing, as before.

## 0.11.7

- A "Machiya · status" row in the Rooms menu and a link from the footer's "Part of Machiya" to the stack's status page; `GET /api/changelog` serves this changelog for its recent deploys, and `/api/health` names the vendored vaultkit (vaultkit 0.18.0).

## 0.11.6

- A search pill under the header on every page, at every width, as Shiori's: results appear as you type, Escape or the X puts the page back, and on a phone a magnifier submits (vaultkit 0.17.2). The Search tab and nav link are gone; the tab bar has its old tabs again.

## 0.11.5

- In the installed app on an iPhone the header's logo and title sit lower, clear of the band under the status bar that iOS draws soft; the phone header is pinned again (vaultkit 0.16.8).

## 0.11.4

- On a phone the header scrolls with the page instead of staying pinned (vaultkit 0.16.7): the installed app on iOS drew a pinned header soft. The Rooms menu's text meets AA contrast in every theme.

## 0.11.3

- On a phone the tabs are Board, Now, Search and Roundup (then Rooms): Search is third, as in every room; Review is a button at the top of Now. On a wide screen Search is the third nav link.
- No search field in the header at any width, and the header is solid on a phone (vaultkit 0.16.4): the installed app on iOS drew the header's blur over its own title.

## 0.11.2

- The phone tab bar is more see-through, frosted glass like Shiori's (vaultkit 0.16.1). 0.11.1 was tagged but never deployed.

## 0.11.1

- On a phone the tab bar is a floating pill like Shiori's (vaultkit 0.16.0): it fits five tabs on any phone, the current tab sits on a raised pill, and it follows the light or dark variant as Shiori does.

## 0.11.0

### Security

- `KANBAN_AUTH=open` answers only requests whose `Host` is an IP address, `localhost`, `KANBAN_BOARD_URL`'s host or a
  name in the new `KANBAN_ALLOWED_HOSTS` (case, port and a trailing dot don't matter); others get 403. A web page that
  pointed its own name at the board's machine (DNS rebinding) could read and change the board, since its `Origin`
  and `Host` agree. If other rooms call Konbini by a name (`http://konbini:8081` in the reference compose), list it in
  `KANBAN_ALLOWED_HOSTS`.
- After a form post and from the `/theme` fallback, the board redirects back to the `Referer`'s path only when it is
  on this site: `//host`, `/\host` and paths with control characters (a tab between the slashes, for example) used to
  send the browser to another site; they now go to the card or to `/`.
- API writes (`/api/…`) from anything but the board's own pages must send `X-Agent` and no `Origin` or `Referer`, as
  machiya-mcp, Niwa and `tools/pm` already do. Before, another site's page could post a form or plain text to the API
  while the owner browsed it, and the write went through under the owner's login (CSRF). A cross-site `Origin` or
  `Referer` (including `Origin: null`), or a write naming no caller, now gets 403.
- No GET changes the board: `/p/<slug>/tags?remove=` removed a tag on a plain link, so an `<img>` on any page could
  do it while the owner browsed. The card page's form already posts; the GET route is gone.
- **Identity** (Machiya's identity plan, phase 4; vaultkit v0.10.0): with `MACHIYA_IDENTITY_FILE`, Konbini asks the
  identity file who is calling (a token, a Tailscale login or tagged node, a trusted proxy header, a session) instead
  of `KANBAN_TAILNET_USERS`, and what they may do: the `konbini` grant `read` for pages and read APIs, `write` for
  card edits, comments, claims and the board's forms, `areas` for new `area/*` lanes and new tags. `areas` replaces
  the old test for the owner's powers (a same-origin request without `X-Agent`), which any client the gate admitted
  could pass by sending the right headers. No proof or a bad one is 401, a missing grant 403. An event's `actor` is
  the principal's name; `X-Agent` stays a label. New settings: `KANBAN_AUTH=header` with `KANBAN_AUTH_HEADER`,
  `KANBAN_BIND_BEHIND_PROXY`, `KANBAN_ACCEPT_APP_CAPS`. Without the file nothing changes.
- **A note's HTML never runs** (vaultkit 0.13): the writing kit's page quoted the note (its overview, code, Log rows
  and links) as python-markdown rendered it, so a `<script>`, an `onerror` or a `javascript:` link in a note ran on
  the kit page. It goes through vaultkit's sanitizer now. Every page also carries vaultkit's security headers (a
  Content-Security-Policy allowing only the board's own scripts, `nosniff`, a same-origin `Referer`); the board's
  markup has no inline handler left.

### Added

- **Sign-in, pairing and preferences** (the identity plan's phase 6; vaultkit v0.11.0): with the identity file,
  `KANBAN_SIGNIN=1` turns on the built-in sign-in (`GET/POST /signin`, a session cookie; a browser's 401 page links
  to it) and `POST /signout` (Settings → Account → Sign Out). `POST /api/pair` trades a pairing code from the CLI
  for a Shiori device token. `GET/PUT /api/prefs` keeps each principal's preferences in `prefs.sqlite3` next to
  `KANBAN_DB`. The sign-in, sign-out and preference checks accept `KANBAN_BOARD_URL`'s origin; over plain http, set
  it to the board's `http://` address. Pairing and token-made preference changes need no `X-Agent`. Without the
  identity file sign-in and pairing are 404; preferences (vaultkit 0.12) are the person the old gate let in.
- The header shows who is signed in (identity file), and Settings has an Account section for them.
- The installed app: shortcuts (Board, Now, Review, New Card), a category, and sharing a page to Konbini opens the
  Capture form prefilled (the share target is a GET; the POST one was refused by the same-origin rule).
- An empty column says "No cards"; on a phone the column tabs fade at the right edge, a hint that they scroll.

### Changed

- vaultkit 0.13: the shared 401, 404 and offline pages, "Title - Konbini" titles, the status bar follows the theme.
- The icon files are `konbini-*`; the old `kanban-*` addresses answer 301. The browser keeps the board's own choices
  under `konbini.*` (the old `kanban.*` values move over once).
- A write made offline (a card move, an edit, a new card) stays on the page and says it wasn't saved, instead of the
  browser's error page or an alert. The card sheet links Niwa only when it is configured and the note is published,
  adds View in Kura, and says Open in Obsidian like the card page.

### Fixed

- With the identity file, `/api/status` and `/api/health` give their details (Hister's address, sync and Hister
  error texts) to the owner only; others with `read` get `ok`, `version`, `head`, `cards`, `auth` and `error`.
- A write with an unreadable `Content-Length` answers 400, one with a body over 1 MiB 413 (the body is read and
  dropped first, so the client sees the answer), and an API write whose JSON body is not an object 400; each used to
  drop the connection or wait for bytes that never came.
- A claim with a `minutes` that is not a whole number, and an edit to a card whose note's frontmatter stopped being
  valid YAML since the board indexed it (a phone edit, say), answer 422 instead of dropping the connection.
- The listener drops a client that stalls for 30 seconds mid-request (or doesn't read the answer), so stalled
  connections no longer hold a thread each for good.
- The card page's tag form (`POST /p/<slug>/tags`) adds and removes tags again: it reached the card's own form
  handler, which saw no fields and changed nothing.

## 0.10.2

### Added

- A Quickstart in the README: Konbini on its own with a sample vault (podman or docker; natively on Debian, Ubuntu,
  OpenBSD, FreeBSD and NetBSD) and as part of the Machiya stack, with what you should see at each step.
- `sample-vault/` and `tools/demo-vault`: a small invented vault (ten cards across every column, three streams, two
  goals) and the script that turns it into a git repository.
- `tools/quickstart-test` runs the README's Quickstart commands from a fresh checkout and checks their output;
  `tools/screenshots` makes the pictures in the README from the sample vault.

### Fixed

- A table alias written `[[Note\|alias]]` now links to the note (it used to stay plain text), so a card's and a note's
  link and backlink counts can rise slightly.
- A callout without a title no longer swallows the line after it.

## 0.10.1

### Fixed

- `pm` explains an HTTP 405 from the board as "no such write endpoint" and points at `KANBAN_URL`; `pm --help` shows
  the command list and the settings it reads.
- Documentation and comments describe what the code does: the card rule, the cold-archive map format, the pm
  commands and the settings.

## 0.10.0

### Added

- **`tools/pm`**: a one-file command line for a board (Python 3, standard library only): list and show cards, create
  them, move, set the next action, block, log, tag, set dependencies, workstream, goal and due date, claim, the weekly
  review, roundups and writing kits. It reads `KANBAN_URL` (default `http://127.0.0.1:8081`) and `KANBAN_AGENT`;
  `pm suggest` needs `NIWA_URL` and is off without it. See "The pm command line" in the README.

## 0.9.0

### Defaults (set these for the other behaviour)

- `KANBAN_REPO_SUBDIR` is empty, so the notes are read from the repository root. If your notes live in a folder, set
  `KANBAN_REPO_SUBDIR` to it (and, in stack mode, name the same folder in `KANBAN_REPO_SPARSE`).
- `KANBAN_BLOG_PERMALINK` is `/{year}/{slug}/`: the path of a post's page under `KANBAN_BLOG_URL`, which the writing
  kits link to. Set it to your blog's pattern (for example `/blog/{year}/{slug}/`).

### Added

- `KANBAN_BLOG_PERMALINK`. The README documents the blog layout the kits expect (`_posts/` files, optional
  `tag/<tag>.md` pages), the file format behind `KANBAN_LIVESYNC_STATUS`, the `MACHIYA_SOURCE_URL` and
  `MACHIYA_COOKIE_DOMAIN` settings, the dated-table and status-block formats the calendar, roundups and kits read,
  and an introduction to the Machiya services.

## 0.8.0

The first numbered release. Konbini is a project board built from a git repository of Markdown notes with YAML
frontmatter (an Obsidian vault works as it is): a kanban board, a weekly review, dependencies, workstreams, goals and
due dates, a timeline and calendar, search, and writing kits.

### Defaults (set these for the other behaviour)

- `KANBAN_ARCHIVE` is `none`: the link checker visits the links in cards' notes to see if they are alive, and never
  contacts the Wayback Machine. Set `KANBAN_ARCHIVE=wayback` to also ask it for snapshots and save them (any other
  value counts as `none` and logs a warning).
- `KANBAN_HISTER_SAVE` is off: with `KANBAN_HISTER_URL` set, Konbini shows Hister's existing copy of a link
  (a read-only lookup). Set `KANBAN_HISTER_SAVE=1` (or `on`, `true`) to index live links Hister does not have yet.
- The calendar, roundups and writing kits leave out the board's own `board: ` commits and merges. Add more commit
  subject prefixes with `KANBAN_SKIP_COMMITS` (everywhere) and `KANBAN_CALENDAR_SKIP_COMMITS` (calendar and roundups
  only), comma-separated and case-insensitive.
- The writing kits map a card's topics and area onto a blog's tags and categories through `.board/kit.json` in the
  repository: `tag_synonyms`, `area_category`, `default_category`, `ignore_tags` and `ignore_categories`. Without the
  file the kit uses the blog's own tags and categories.
- The New-card form offers the repository's `area/*` tags; a repository with none yet gets a text box for its first
  lane (confirmed on submit).

### Added

- `GET /healthz`: open, answers `ok`, independent of `KANBAN_AUTH`; the container image has a `HEALTHCHECK` that uses
  it. `/api/status` stays behind the identity check and reports `version`; Settings → About shows it.
- `KANBAN_REPO_SUBDIR`, `KANBAN_EXPORT_IDLE`, `KANBAN_EXPORT_MAX`, `KANBAN_PULL_SECONDS`, `KANBAN_VERIFY_SECONDS`,
  `KANBAN_WIP_LIMITS`, `KANBAN_SKIP_COMMITS`, `KANBAN_CALENDAR_SKIP_COMMITS`, `KANBAN_ARCHIVE`, `KANBAN_HISTER_SAVE`;
  the README table lists every setting. `MACHIYA_SOURCE_URL` (from the shared vaultkit) adds a "Source code" link to
  the footer and About; it is unset by default.
- A repository with no commits or no `origin` starts quietly and keeps its commits local, with one plain line in the
  log.
- README sections for a standalone install, the vault layout and every setting; `CONTRIBUTING.md`, `SECURITY.md`.

### Behaviour

- The board writes the field names `status`, `waiting` and a `priority` word, and no `status/*` tags. Notes that
  still use the old names (`board`, `blocked_by`, `date`, integer `priority`, `status/*` tags) are not read; they are
  listed under `legacy_names` in `/api/status`. The API keeps `board`, `blocked_by`, an integer `priority` and an
  old-style `status` on cards and accepts the old names as input, so `/api/cards` consumers are unaffected.
- The writing kit's related notes are sorted, so their order is stable.

### Also in this line

Board with drag and drop, claims and an event history; frontmatter-line edits batched into git commits with a pull,
rebase and replay that never stashes; weekly review with per-area WIP limits; dependencies, workstreams, goals and due
dates, with a timeline, calendar and roundups; one search field; link-rot checking; writing kits; an installable web
app with an offline page; `tailscale` or `open` access modes; native installs with `--env-file`.
