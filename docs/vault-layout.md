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
- **Blog tags.** An optional `.board/kit.json` maps a card's topics and area onto your blog's tags and categories
  (`tag_synonyms`, `area_category`, `default_category`, `ignore_tags`, `ignore_categories`). Without it, the blog's own
  tags and categories drive the kit.
- The frontmatter fields are in `docs/frontmatter.md` of the [Machiya repository](https://github.com/machiya-kobo/machiya).
