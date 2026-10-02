# Contributing to Konbini

Konbini is a small, dependency-light Python web app (the standard library plus `markdown` and `pyyaml`). Bug reports,
fixes and focused features are welcome. By contributing you agree that your work is licensed under the project's
licence, AGPL-3.0-or-later (see `LICENSE`).

## Before you start

- **Open an issue first** for anything bigger than a small fix, so we can agree on the shape of it. Konbini is one
  half of Machiya (a few small services that share a vault of notes), and some behaviour is a contract with its
  sister services (`/api/cards`, `/api/digest`): those stay stable.
- **Security problems** go to the private channel in `SECURITY.md`, not to the issue tracker.

## Working on the code

`CLAUDE.md` is the contributor guide: the layout, the rules the code relies on, and the traps. Read it first. In short:

- Pages are plain HTML5 built by `app/modern.py` on the shared shell in `app/vaultkit/`. The board page stays small
  (about 100 KB). No front-end build step.
- **Do not edit `app/vaultkit/`.** It is vendored from the Machiya `vaultkit` and the build fails on drift. Fix it
  upstream, tag it, then re-vendor with `tools/vendor-vaultkit <tag>` (set `VAULTKIT_REPO`).
- The board only edits **frontmatter lines**, never note bodies, and never rewrites history in `.board/events`.
- A new setting gets a `KANBAN_*` name, a default that is safe for a public install, and a row in the README table.

## Tests

```sh
tests/run.sh                        # every tests/test_*.py; needs python3 with markdown and pyyaml, git, sqlite3
KONBINI_TEST_PYTHON=~/venv/bin/python tests/run.sh
tests/run.sh --image IMAGE          # or inside the built image, as uid 1000
```

Each test builds its own throwaway vault and listeners; none touches a real board. Add a test with a change: the
existing ones (`tests/test_writer.py`, `tests/test_fresh.py`) show the pattern. Run the whole suite before sending a pull
request.

## Pull requests

- Keep a change focused, and describe what it does and why. Include how you tested it.
- Match the surrounding code: naming, comment density, idiom. No reformatting of code you did not change.
- Commit messages start with `konbini: ` and say what changed.
