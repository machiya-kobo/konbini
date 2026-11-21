# Vault layout

Konbini reads a git repository of Markdown notes, at its root or in one folder (`KANBAN_REPO_SUBDIR`). An Obsidian
vault works as it is.

- **Cards.** A card is a note whose `status:` is a board column. New cards go to `Projects/<Title>.md`, tagged
  `type/idea`, `area/projects` and one `area/<lane>`. The lane is the first area tag other than `area/projects`.
- **Description.** The text under a note's title heading, up to the next heading. The board shows it on the card
  page and writes it from the card form, the API and `pm`; everything below it is yours and stays as it is. Writing
  kits use it as the overview. It can't contain headings. New cards start with the description you give them, or
  their summary.
- **Projects.** A card's `stream:` is its project: cards that share one group together (Plan → Streams, and Group By
  → Stream on the board). The swimlane is the `area/*` tag; the card page changes it to an area that exists.
- **New topics.** A new `topic/*` tag is yours to create. An agent that can write may create one only by naming it in
  `new_topics` when it adds the tag, which it does after you said yes. The card's history in `.board/events` records a
  `topic_created` event with the tag, who and which agent. A new `area/*` tag (a new swimlane) stays yours to create.
- **Closing a card.** `status: archived` takes a card off the board and keeps the note. Archive and Won't do both do
  that. Won't do also records why in `.board/events` (not in the note) and keeps the card out of Posts, the list of
  finished projects to write up. Move an archived card back to a column to reopen it.
- **Dated rows.** The calendar, roundups and writing kits read dated table rows from any note:
  `| 2026-01-15 | milestone | Shipped | details |` (a date, a category, a change, then anything). A card's `## Log`
  table gives its milestones. Tables in notes under `Systems/` give machine changes, named by the note's `host:`
  (monthly notes such as `Systems/Change Logs/<host> 2026-10.md`) or its title. Without those notes the pages
  just have fewer rows.
- **Commits.** A card's note may hold a generated block between `<!-- project-sync:start -->` and
  `<!-- project-sync:end -->`. Its `- YYYY-MM-DD: commit subject` bullets stand in for the repository's recent commits
  when the kit can't fetch them.
- **Now.** The Now page lists the cards with something in the last 7 days: commits on the card's repos, board events
  and claims, change-log rows that link the card's note (`[[Projects/<Title>]]`), and its own dated rows. A card's
  repos are its `repos:` list, else its `repo:`. Set them on the card page (Repos: add, remove, or Confirm the one
  `repo:` gave), with `pm repos`, or with `repos` in a PATCH. The board writes the `repos:` list and drops a `repo:`
  line in the same edit. A name is 1-100 letters, digits, `.`, `_` or `-`; a URL counts as its last part, `.git`
  dropped. A repo's commits come from its checkout under `KANBAN_REPOS`, else
  from its note `<name>.git.md` (anywhere in the vault): the note's `- YYYY-MM-DD: subject` bullets and
  `last_commit:`, matched by the note's name or the last segment of its `forgejo:` or `github:` URL. Change-log rows
  under `Systems/Change Logs/` that link no card are listed by host, except rows whose change text starts with the
  robot emoji (🤖, the triage agent's: incidents track those). Such a row that links a card still counts for it.
  With `KANBAN_BUS_URL` set ([settings](settings.md#agents-now)), Agents Now at the top lists the agents working
  right now and their cards; an agent on a card counts for it like a claim.
- **Blog tags.** An optional `.board/kit.json` maps a card's topics and area onto your blog's tags and categories
  (`tag_synonyms`, `area_category`, `default_category`, `ignore_tags`, `ignore_categories`). Without it, the blog's own
  tags and categories drive the kit.
- The frontmatter fields are in `docs/frontmatter.md` of the [Machiya repository](https://github.com/machiya-kobo/machiya).
