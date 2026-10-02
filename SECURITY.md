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
- **What it can do.** It reads and edits the frontmatter of the notes in its own clone of your vault and pushes
  commits. Anyone allowed in can change cards. Form posts must be same-origin; API writes identify themselves with
  `X-Agent` (a label, not authentication).
- **`GET /healthz`** is deliberately open and returns only `ok`.
- **Outbound.** The link checker visits the links in card notes. It contacts the Wayback Machine only with
  `KANBAN_ARCHIVE=wayback`, and indexes pages into Hister only with `KANBAN_HISTER_SAVE=1`.

## Supported versions

Only the latest release (and `main`) receives fixes.
