# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue: use GitHub's private vulnerability reporting (this
repository's Security tab, then Report a vulnerability), with what you found, how to reproduce it, and what it affects.
You'll get an answer within a week, and a fix or a plan before anything is disclosed.

## What Konbini trusts

Know this before you deploy it:

- **Who may use it.** `KANBAN_AUTH=tailscale` (the default) accepts only requests whose `Tailscale-User-Login` header
  is in `KANBAN_TAILNET_USERS`, and relies on `tailscale serve` (or another proxy you control) to set that header and
  to strip any client-supplied copy. **Bind to `127.0.0.1` behind it**: on a public bind anyone who can reach the port
  can send the header. `KANBAN_AUTH=open` turns the identity check off entirely, for localhost or a trusted LAN only; it still answers
  only requests whose `Host` is an IP address, `localhost`, `KANBAN_BOARD_URL`'s host or a name in
  `KANBAN_ALLOWED_HOSTS`, so a web page using DNS rebinding can't reach the board.
- **The identity file** (`MACHIYA_IDENTITY_FILE`, Machiya's identity plan). Set, it replaces `KANBAN_TAILNET_USERS`:
  a token, a Tailscale login or tagged node, a trusted proxy's login header (`KANBAN_AUTH=header`) or a session names
  the principal, and only its `konbini` grants decide: `read` for pages and read APIs, `write` for any change,
  `areas` for new `area/*` lanes and new tags. Headers such as `Origin` or a missing `X-Agent` no longer give owner
  powers. A missing or bad proof is 401 and never falls through to another proof. In `tailscale` and `header` mode the
  board refuses to start on a non-loopback bind unless `KANBAN_BIND_BEHIND_PROXY=1` says the proxy is the only way in.
  The file holds only hashes; mount its directory read-only. Report a principal doing more than its grants allow, or
  a proof accepted that shouldn't be.
- **Sign-in, pairing and preferences** (with the identity file; vaultkit `signin`). `/signin` (`KANBAN_SIGNIN=1`),
  `/signout` and `/api/pair` answer before the gate, after open mode's `Host` rule. Sign-in and sign-out must be
  same-origin with `KANBAN_BOARD_URL`'s origin (or, without it, an https page naming the request's own `Host`); over
  plain http without `KANBAN_BOARD_URL` every sign-in is refused, since `Host` and `Origin` there prove nothing (DNS
  rebinding). Passwords are scrypt hashes, failures are throttled per name and per address (behind a proxy every
  client shares the address), and the answer never says whether the name exists. Pairing trades a 10-minute code
  from the CLI for a device token (5 tries per address per 10 minutes) and reads no cookie. `GET/PUT /api/prefs`
  needs `read`; a PUT not proven by a token must be same-origin, `X-Agent` notwithstanding. Bodies are capped (4 KB
  sign-in, 1 KB pairing, 512 KB preferences) and refused with 413 before they are parsed. With sign-in on, the shared
  stylesheet, script and icons answer without a proof (they are vendored files, no board data).
- **What it can do.** It reads and edits the frontmatter of the notes in its own clone of your vault and pushes
  commits. Anyone allowed in can change cards (with an identity file: anyone with the `write` grant). Form posts must be same-origin; API writes from outside the board's
  pages identify themselves with `X-Agent` (a label, not authentication) and must not carry another site's `Origin`
  or `Referer`, so a page you browse can't write the board as you (CSRF).
- **`GET /healthz`** is deliberately open and returns only `ok`.
- **Outbound.** The link checker visits the links in card notes. It contacts the Wayback Machine only with
  `KANBAN_ARCHIVE=wayback`, and indexes pages into Hister only with `KANBAN_HISTER_SAVE=1`.

## Supported versions

Only the latest release (and `main`) receives fixes.
