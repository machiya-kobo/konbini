"""Card dependencies: `dependsOn: ["[[Project]]", ...]` (the Machiya frontmatter schema).

Each link resolves with vaultkit's wikilink rules (the vault index: lowercased file name, then the last path
segment, the path itself), falling back to a card's slug or title. A card is *waiting on* every dependency that
isn't done or archived; while it waits it counts as blocked, like the Blocked column and a `waiting:` reason
The inverse is *unblocks*. Nothing here is stored: it's derived per request.
"""
import re

DONE = ("done", "archived")


def build(cards, resolve):
    """{slug: {"waits_for": [card], "unblocks": [card], "waiting_on": [card], "unresolved": [text]}}.

    resolve(target) -> a vault path ("Projects/X.md") or None (vaultkit's Vault.resolve)."""
    by_path = {c["path"]: c for c in cards}
    by_key = {}
    for c in cards:
        by_key.setdefault(c["slug"].lower(), c)
        by_key.setdefault(c["title"].lower(), c)
    out = {c["slug"]: {"waits_for": [], "unblocks": [], "waiting_on": [], "unresolved": []} for c in cards}
    for c in cards:
        for target in c.get("dependsOn") or []:
            rel = resolve(target)
            dep = by_path.get(rel) if rel else None
            dep = dep or by_key.get(target.lower()) or by_key.get(target.split("/")[-1].lower())
            if not dep or dep["slug"] == c["slug"]:
                out[c["slug"]]["unresolved"].append(target)
                continue
            if dep not in out[c["slug"]]["waits_for"]:
                out[c["slug"]]["waits_for"].append(dep)
                out[dep["slug"]]["unblocks"].append(c)
                if dep.get("board") not in DONE:
                    out[c["slug"]]["waiting_on"].append(dep)
    return out


def decorate(cards, graph):
    """Copies of the cards with `_waiting_on` (titles) for the board's cards, the review and the card page."""
    return [dict(c, _waiting_on=[d["title"] for d in graph.get(c["slug"], {}).get("waiting_on", [])]) for c in cards]


def link_for(card):
    """The quoted wikilink the board writes for a dependency: the note's file name."""
    stem = card["path"].rsplit("/", 1)[-1]
    return "[[%s]]" % (stem[:-3] if stem.endswith(".md") else stem)


def mermaid(cards, graph):
    """A Mermaid flowchart of every card in a dependency (archived ones left out): dependency --> dependent,
    nodes coloured by column."""
    involved = {s for s, g in graph.items() if g["waits_for"] or g["unblocks"]}
    live = [c for c in cards if c["slug"] in involved and c.get("board") != "archived"]
    if not live:
        return ""
    nid = {c["slug"]: "n%d" % i for i, c in enumerate(live)}

    def label(c):
        return re.sub(r'["\[\]{}()<>|#;]', " ", c["title"]).strip() or c["slug"]
    lines = ["flowchart LR"]
    for c in live:
        lines.append('  %s["%s"]:::%s' % (nid[c["slug"]], label(c), c.get("board") or "none"))
    for c in live:
        for dep in graph[c["slug"]]["waits_for"]:
            if dep["slug"] in nid:
                lines.append("  %s --> %s" % (nid[dep["slug"]], nid[c["slug"]]))
    lines += ["  classDef backlog stroke:#565f89", "  classDef ready stroke:#7aa2f7,stroke-width:2px",
              "  classDef wip stroke:#ff9e64,stroke-width:2px", "  classDef blocked stroke:#f7768e,stroke-width:2px",
              "  classDef done stroke:#9ece6a,stroke-width:2px", "  classDef none stroke:#565f89"]
    return "\n".join(lines)
