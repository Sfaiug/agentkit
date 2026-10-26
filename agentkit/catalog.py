"""Which models exist now, and what replaced what, read off Artificial Analysis's records as
`boards.collect` holds them.  A release is one model, its efforts each a row of the board; it is
current while none of its rows is deprecated, and a deprecated one names the release that
replaced it (`deprecatedTo`), which may itself be replaced.  The record's shape (releases,
those chains, the default effort being the row whose slug is the release's own) stays here.
"""

from .boards import EFFORT_ORDER

BOARD = "artificialanalysis.ai"


def _releases(boards):
    """{release slug: its rows}, off rows that carry their record's identity: those an older
    build read carry none, and stand for nothing until a new build has asked again."""
    releases = {}
    for row in (boards.get(BOARD) or {}).get("rows") or []:
        if "release" in row:
            releases.setdefault(row["release"]["slug"], []).append(row)
    return releases


def _release(slug, rows):
    """A release as callers see it: its slug, name and maker, and its efforts weakest first,
    each with its row's slug and whether it is the default."""
    rows = sorted(rows, key=lambda row: EFFORT_ORDER.index(row["effort"])
                  if row["effort"] in EFFORT_ORDER else -1)
    return {"slug": slug, "name": rows[0]["release"]["name"], "maker": rows[0]["maker"],
            "efforts": [{"effort": row["effort"], "slug": row["slug"],
                         "default": row["slug"] == slug} for row in rows]}


def _current(rows):
    return not any(row["deprecated"] for row in rows)


def current(boards):
    """Artificial Analysis's current releases, strongest first by their best
    `aa.intelligenceIndex`; those without one last, by name."""
    def strength(item):
        slug, rows = item
        best = max((row["values"]["aa.intelligenceIndex"] for row in rows
                    if "aa.intelligenceIndex" in row["values"]), default=None)
        return best is None, -(best or 0), str(rows[0]["release"]["name"])
    return [_release(slug, rows) for slug, rows
            in sorted(_releases(boards).items(), key=strength) if _current(rows)]


def successor(boards, slug):
    """The current release the release `slug`'s `deprecatedTo` chain ends at, itself when it is
    current; None when the chain ends anywhere else: a slug the board does not list, a
    deprecated release naming no successor, or a loop."""
    releases, seen = _releases(boards), set()
    while slug in releases and slug not in seen:
        if _current(releases[slug]):
            return _release(slug, releases[slug])
        seen.add(slug)
        slug = releases[slug][0]["release"]["deprecatedTo"]
    return None
