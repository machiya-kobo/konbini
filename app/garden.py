"""The vault as the board sees it: vaultkit.Vault (index, wikilink resolution, the Markdown renderer) over the
board's clone, re-indexed when the board's import moves HEAD or bumps its revision.

Card pages render a card's note with it (published notes link to Niwa), writing kits read notes, links and
backlinks from it, and link rot collects card notes' links from it. The garden itself (published notes, stages,
the pre-publish scan, the queue, the stream's garden half) is Niwa's (machiya-kobo/niwa).
The name stays `Garden` so the call sites didn't change.
"""
from store import VAULT
from vaultkit.vault import Vault


class Garden(Vault):
    def __init__(self, store, timeline):
        super().__init__(store.repo, VAULT, git=store.git)
        self.store = store
        self.timeline = timeline

    def key(self):
        return self.store.meta("head") + self.store.meta("rev")

    def source(self):
        return self.timeline.notes()
