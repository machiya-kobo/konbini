# Who can use it

`KANBAN_AUTH` picks how Konbini knows who is calling, and Machiya's identity file, if you set one, says what each
person or agent may do. Every setting named here is in [Settings](settings.md#access).

- **You, on localhost:** `KANBAN_AUTH=open` and `KANBAN_BIND=127.0.0.1`, as in the Quickstart. No login. Konbini
  answers only to an IP address, `localhost`, `KANBAN_BOARD_URL`'s host or a name in `KANBAN_ALLOWED_HOSTS`.
- **People on your tailnet:** bind `127.0.0.1`, put `tailscale serve` in front, and list their Tailscale logins in
  `KANBAN_TAILNET_USERS` (`KANBAN_AUTH=tailscale`, the default; unset means nobody).
- **People, agents, sign-in or Shiori devices:** Machiya's identity file, off unless you set it.
  `cd app && python3 -m vaultkit.identity setup` (standard library only) prints each app's settings. See
  [Machiya's identity guide](https://github.com/machiya-kobo/machiya/blob/main/docs/identity.md).
- **People signed in to Hister:** `KANBAN_AUTH=hister` with Machiya's hister-login helper (`KANBAN_AUTH_SIGNIN_URL`,
  `KANBAN_AUTH_URL`, `KANBAN_HISTER_USERS`, `KANBAN_BOARD_URL`; see
  [Machiya's Hister sign-in](https://github.com/machiya-kobo/machiya/blob/main/docs/identity.md#hister-sign-in-authhister)).
  Not with an identity file.
- The identity settings are `MACHIYA_IDENTITY_FILE`, `KANBAN_SIGNIN`, `KANBAN_AUTH_HEADER`,
  `KANBAN_BIND_BEHIND_PROXY`, `KANBAN_ACCEPT_APP_CAPS` and `KANBAN_BOARD_URL`, in [Settings](settings.md#access).

## Sign-in, pairing and preferences

Sign-in and pairing exist only with `MACHIYA_IDENTITY_FILE` (vaultkit's `signin`); without the file they answer 404.
Preferences work in every mode. Without the file they belong to whoever Konbini let in (the Tailscale login, or the
owner in open mode), so theme and text size follow that person to another device.

| Route | Gate | What it does |
|---|---|---|
| `GET /signin`, `POST /signin` | before (needs `KANBAN_SIGNIN=1`, else 404) | the sign-in form, and its same-origin post: a session cookie and a 303 to `next` (a local path) |
| `POST /signout` | before | same-origin only: clears the session cookie |
| `POST /api/pair` | before | Shiori's device pairing: `{"code", "device"}` (a code from `python3 -m vaultkit.identity pair <name>`, run in `app/`) gives `{"token", "principal"}`, a device token for `Authorization: Bearer`. Works with or without `KANBAN_SIGNIN` |
| `GET /api/prefs`, `PUT /api/prefs` | after (`konbini` `read`, or the check without a file) | the caller's own preferences, `{"prefs": {key: value}}`; a PUT merges (`null` removes) |

Open mode's `Host` rule comes first. After that, vaultkit's rules apply, not the board's `/api` write rule: pairing
(the code is the proof) and a `PUT /api/prefs` with a token need no `X-Agent` or `Origin`. Any other `PUT /api/prefs`
must come from the board's own page (`Origin`, else `Referer`): `KANBAN_BOARD_URL`'s origin, else an https page
naming the request's `Host`, or in open mode without an identity file that `Host` over http too.

Preferences live per principal in `prefs.sqlite3` next to `KANBAN_DB` (mode 0600), so a cache `rebuild` keeps them.
With an identity file the header shows who is signed in, and Settings has an Account section (Sign Out for a sign-in
session).
