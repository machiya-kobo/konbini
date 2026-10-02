# Changelog

Konbini follows [SemVer](https://semver.org). Before 1.0, a new feature, a changed default or setting, or a changed
API field is a minor bump; a fix, wording or internal change is a patch.

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

### Fixed

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
