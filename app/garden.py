"""The vault as the board sees it: vaultkit.Vault (index, wikilink resolution, the Markdown renderer) over the
board's clone, re-indexed when the board's import moves HEAD or bumps its revision.

Card pages render a card's note with it (published notes link to Niwa), writing kits read notes, links and
backlinks from it, and link rot collects card notes' links from it. The garden itself (published notes, stages,
the pre-publish scan, the queue, the stream's garden half) is Niwa's (machiya-kobo/niwa).
The name stays `Garden` so the call sites didn't change.
"""
import threading

from store import VAULT
from vaultkit.vault import Vault


class Garden(Vault):
    def __init__(self, store, timeline):
        super().__init__(store.repo, VAULT, git=store.git)
        self.store = store
        self.timeline = timeline
        self._index_lock = threading.Lock()

    def index(self):
        """One request builds the index and the others wait for it, instead of each building their own."""
        with self._index_lock:
            super().index()

    def key(self):
        return self.store.meta("head") + self.store.meta("rev")

    def source(self):
        return self.timeline.notes()

    def tended_dates(self):
        """The garden's "tended" dates are Niwa's; nothing here reads them, and vaultkit would run a `git log` over the
        whole history to make them every time the index is rebuilt (after every change to a card)."""
        return {}
