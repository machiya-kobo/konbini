# The pm command line

`tools/pm` is one file of Python 3, standard library only: put it on your `PATH` or run it in place. It talks to
`KANBAN_URL` (default `http://127.0.0.1:8081`) and signs its changes with `X-Agent` (`pm@<host>`, or `KANBAN_AGENT`).

On a `KANBAN_AUTH=hister` board, `KANBAN_TOKEN_FILE` names a file with a room token (`mht_…`, minted for Konbini and
Niwa by the hister-login helper; the owner's Hister token also works). Keep it in your password store, never in an
argument or a note. pm sends it only to the board and Niwa, as `Authorization: Bearer`, over https (http only to this
machine), and follows no redirects meanwhile. An address without a scheme is https.

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

`pm new` and `pm tag` take existing areas and tags only; make a first lane in the web form. `pm suggest <note>` asks
Niwa to consider a note for the garden (needs `NIWA_URL`). If the board is too old for a command (a 405), `pm` says so. The `X-Agent`
label, your host name with it, lands in the card's history in `.board/events`. The `KANBAN_` prefix is from Konbini's
earlier name.

Settings for the board side are in [Settings](settings.md); the board's own HTTP API is described in Machiya's
[docs/contracts/konbini-api.md](https://github.com/machiya-kobo/machiya/blob/main/docs/contracts/konbini-api.md).
