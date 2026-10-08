# CLAUDE.md: working on Konbini

Konbini is a project board built from a git repository of Markdown notes with YAML frontmatter (an Obsidian vault works
as it is). A note whose `status:` is a column (backlog, ready, wip, blocked, done, archived) is a card. SQLite is a cache
and git is the backup: the board rebuilds from the notes plus `.board/` at any time. It is one of the Machiya apps and
runs on its own; Kura, Niwa and Shiori are optional neighbours (their links are off when their settings are unset).
`README.md` is the overview and Quickstart, `docs/` the install guide, access, settings, vault layout and `pm`,
`CONTRIBUTING.md` the workflow. Frontmatter, API contracts and the style guide live in the
[Machiya repository](https://github.com/machiya-kobo/machiya) (`docs/frontmatter.md`, `docs/contracts/`, `docs/style-guide.md`).

## Set up, run, test

```sh
python3 -m venv .venv && .venv/bin/pip install 'markdown>=3.11' pyyaml    # Python 3.11 or later; git, sqlite3 and openssl too
tools/demo-vault demo-vault && mkdir demo-data                              # the sample vault as a git repository
KANBAN_REPO="$PWD/demo-vault" KANBAN_REPO_SUBDIR=personal KANBAN_DB="$PWD/demo-data/konbini.sqlite3" \
  KANBAN_AUTH=open KANBAN_BIND=127.0.0.1 .venv/bin/python app/app.py       # http://127.0.0.1:8081/
KONBINI_TEST_PYTHON=.venv/bin/python tests/run.sh                          # every tests/test_*.py, each on its own throwaway vault
```

Playwright for Python (with Chromium) is needed for `tests/test_outbox.py` and `tests/test_contrast.py`; they skip without it.
`tools/quickstart-test` runs the marked blocks in `README.md` and `docs/install.md`; `tools/screenshots` remakes the README's
pictures from the sample vault. There is no linter or formatter: match the surrounding code (naming, comment density, idiom).
Test against a throwaway vault, never a real one.

## Layout

- `app/`: the server. `app.py` routes and listener; `store.py` import, index, events, claims; `writer.py` frontmatter edits
  and the batched git export; `modern.py` the pages (HTML5, on the shared Machiya shell) and `/settings`; `common.py`
  filters and helpers; `deps.py`, `goals.py`, `review.py`, `timeline.py`, `digest.py`, `kit.py` (writing kits), `blog.py`,
  `links.py` (link rot), `hister.py`, `garden.py` (the vault index, a thin vaultkit `Vault`), `urlnorm.py` (the URL rule;
  an identical copy lives in Niwa: keep them in step); `static/` is `board.css`, `board.js`, `outbox.js` and the icons.
- `app/vaultkit/` is the shared vault core, **vendored** from the Machiya repository. **Never edit it**: the build runs
  `python3 -m vaultkit.verify` and fails on drift. Change it upstream, then `VAULTKIT_REPO=<machiya checkout>
  tools/vendor-vaultkit <tag>`.
- `tests/`, and `tools/`: `pm` (the command line, a standard-library client of the HTTP API), `demo-vault`,
  `vendor-vaultkit`, `quickstart-test`, `screenshots`, `Dockerfile.dev` (the image without the optional Hister stage),
  `tsproxy.py` (stands in for `tailscale serve`).

## What the code relies on

- **Writes touch frontmatter lines only**, as line edits (never a YAML load and dump: it reorders keys and conflicts with the
  next export), and never a note body except **the description**, the text under the note's title up to the next heading
  (`writer.lead_of` / `set_lead`). It can't contain a heading or an open code fence (422). The garden's fields (`publish`,
  `growth`, `confidence`, `garden_pin`) belong to Niwa; the board refuses `publish` (403). New `topic/*` and `area/*` tags
  are the maintainer's to create; an agent write that would add one is refused.
- **The `/api/cards` and `/api/digest` contract is stable** (Niwa and Shiori read it): the card keeps `board`, `blocked_by`,
  an integer `priority` and an old-style `status` even though notes use `status`, `waiting` and `priority: high|normal|low`.
  The old field names are not read; such a note is logged and listed under `legacy_names` on `/api/status`.
- **Events** go to `.board/events/*.jsonl` and are never rewritten. The git export batches edits (`KANBAN_EXPORT_IDLE`,
  `KANBAN_EXPORT_MAX`), pulls between batches (never a stash), rebases with a replay when upstream moved, and never commits
  conflict markers (`CONFLICT_RE`).
- **Access.** `KANBAN_AUTH=tailscale` (default) trusts a `Tailscale-User-Login` header from the proxy in front: bind
  `127.0.0.1` behind it, or name the proxies in `KANBAN_TRUSTED_PROXIES` (header-trusting modes refuse a public bind without
  it). `open` has no identity check but answers only an allowed `Host` (DNS rebinding). Form posts must be same-origin; API
  writes that aren't need `X-Agent` and no `Origin`/`Referer` (CSRF). With `MACHIYA_IDENTITY_FILE` the file is the gate
  (`Handler.who()`, `Handler.can()`; sign-in, pairing, `/api/prefs`). `tests/test_auth.py` (no file), `test_identity.py` and
  `test_signin.py` cover it; `GET /healthz` is open.
- **A note is data, never code.** Card pages render a card's description and writing kits quote the note, both through
  `vaultkit.sanitize.clean`. Every HTML answer carries a CSP with `script-src 'self'`: no inline `<script>` and no `on…=`
  attribute; behaviour goes in `board.js`.
- **Hister is optional and single-user:** every call sends `Origin: hister://`, and never `hister index --force` a URL it
  already has. Saving into Hister is off unless `KANBAN_HISTER_SAVE`; the Wayback lookup unless `KANBAN_ARCHIVE=wayback`.
- **Stack mode** (optional): `KANBAN_REPO_REFERENCE` borrows another clone's objects, `KANBAN_REPO_SPARSE` checks out only
  what the board reads and writes.
- **Speed** (`tests/test_perf.py`): a note is read and parsed once per change (`Store.load`, `Timeline.read_changed`). Don't
  loop over `store.cards()` or `store.events()` inside a loop over cards, don't run a `git log` per note, and keep the
  indexes on `events`. Text answers over 1 KB are gzipped.
- **The outbox** (`static/outbox.js`): a move, edit, note or new card that can't reach the board waits in IndexedDB, marked
  "waiting", and goes out in order with what it was based on, so the board's 409 rule applies. `tests/test_outbox.py`.

## Look and rules

- Pages follow the Machiya style guide: `.segmented` for view switches (Group By), `.pills` for filters, `.chip` (outlined, in
  `--chip`) for state, `.chip.link` for links that open something, `.tag` for topics, and the shared `.card` (tinted by its
  column; Settings → Card Style: Tint, Solid, Left Bar, None). Headings are Title Case as written. Colours on raised surfaces
  use the panel shades; `tests/test_contrast.py` measures every page at 4.5:1 (`KONBINI_CONTRAST_PALETTES=all` for all ten
  palettes) and must stay green.
- Modern HTML only; the board page stays small (about 100 KB for the sample vault); no front-end build step.
- A new setting gets a `KANBAN_*` name, a default that is safe for a public install, and a row in `docs/settings.md`.
- American English in docs and UI text (the Machiya `docs/voice.md`): Title Case labels, short words.
- **Never commit personal details or settings.** The repository ships neutral defaults. Hostnames, tailnet names, people's
  names, logins and emails, device names, vault and folder names, tokens, and anyone's own choices or settings (`.env`
  files, `identity.toml`, `prefs.sqlite3`, data) stay outside it. Code, tests, docs, comments, screenshots and commit
  messages use `example.com`, `example.ts.net`, "the user" and the sample vault. Check your diff before you push.
- Commit messages start with `konbini: `. Run the tests before you send a change.
