"""Which models exist now, and what replaced what, read off Artificial Analysis's records as
`boards.collect` holds them.  A release is one model, its efforts each a row of the board; it is
current until replaced (`_replaced`), and a deprecated one names the release that
replaced it (`deprecatedTo`), which may itself be replaced.  The record's shape (releases,
those chains, the default effort being the row whose slug is the release's own) stays here, and
so does which release another board's model is: boards name models their own way and know
nothing of releases.
"""

import re

from .boards import effort_rank

BOARD = "artificialanalysis.ai"
# an eight-digit date in a name, which matches as its last four digits too
DATE = re.compile(r"(?<!\d)20\d\d(\d{4})(?!\d)")
BRACKET = re.compile(r"\s*\(([^()]*)\)")
# what a bracket holding nothing but dates and sizes holds: `(32K, 20251101)` names no variant
DATE_OR_SIZE = re.compile(r"20\d\d-?\d\d-?\d\d|\d{4}|\d+(\.\d+)?[kmb]", re.IGNORECASE)
INTERVAL = (".lower95ci", ".upper95ci")    # a value's interval, `<column>` + each


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
    each with its row's slug, whether it is the default and its row's numbers."""
    rows = sorted(rows, key=lambda row: effort_rank(row["effort"]))
    return {"slug": slug, "name": rows[0]["release"]["name"], "maker": rows[0]["maker"],
            "efforts": [{"effort": row["effort"], "slug": row["slug"],
                         "default": row["slug"] == slug, "values": dict(row["values"])}
                        for row in rows]}


def _names(name):
    """The forms a name matches as: its letters and digits alone, ignoring case, and so again
    with each eight-digit date cut to its last four digits."""
    return {"".join(char for char in form.casefold() if char.isalnum())
            for form in (name, DATE.sub(r"\1", name))}


def _board_names(name):
    """`_names` of another board's model name, its brackets of dates and sizes dropped; none
    where another bracket is left, which names a variant of the model (`Acme 7 (Instant)`)."""
    name = BRACKET.sub(lambda found: "" if all(DATE_OR_SIZE.fullmatch(part) for part
                                                in found.group(1).replace(",", " ").split())
                       else found.group(0), name)
    return set() if "(" in name else _names(name)


def _effort(release, effort):
    """The release's effort a board's row at `effort` measures: the one it names, the default
    where it names none, else the release's only effort; None where none is."""
    efforts = release["efforts"]
    return next((each for each in efforts
                 if (each["effort"] == effort if effort else each["default"])),
                efforts[0] if len(efforts) == 1 else None)


def _join(values, row):
    """A board's row's numbers into an effort's `values`, the lowest of a column kept, since a
    doubt never counts in a model's favour, with its interval from the same row."""
    for column, value in row.items():
        if column.endswith(INTERVAL) and column.rsplit(".", 1)[0] in row:
            continue
        if column not in values or value < values[column]:
            for name in (column, *(column + end for end in INTERVAL)):
                if name in row:
                    values[name] = row[name]
                else:
                    values.pop(name, None)


def _replaced(releases):
    """{slug: what replaced it, or None}: each release with a row deprecated, by the first
    `deprecatedTo` its rows name, and with it each release under its name but the one its chain
    ends at, a variant (AA kept `GPT-6 Sol (Daybreak Blue)`, named GPT-6 Sol, current)."""
    replaced = {slug: next(filter(None, (row["release"]["deprecatedTo"] for row in rows)), None)
                for slug, rows in releases.items() if any(row["deprecated"] for row in rows)}
    for slug in list(replaced):
        end, name = _end(releases, replaced, slug), releases[slug][0]["release"]["name"]
        replaced.update({other: end for other, rows in releases.items() if end and other != end
                         and other not in replaced and rows[0]["release"]["name"] == name})
    return replaced


def _end(releases, replaced, slug):
    """The release the chain of `replaced` from `slug` ends at, `slug` itself when it is
    current; None at a slug the board does not list, a release replaced by none, or a loop."""
    seen = set()
    while slug in replaced and slug not in seen:
        seen.add(slug)
        slug = replaced[slug]
    return slug if slug in releases and slug not in replaced else None


def current(boards):
    """Artificial Analysis's current releases, strongest first by their best
    `aa.intelligenceIndex`; those without one last, by name.  Each effort's `values` carry,
    beside its own row's, those of every other board's rows naming the release (`_board_names`
    meeting `_names` of its name, and of no other current release's) at that effort."""
    def strength(item):
        slug, rows = item
        best = max((row["values"]["aa.intelligenceIndex"] for row in rows
                    if "aa.intelligenceIndex" in row["values"]), default=None)
        return best is None, -(best or 0), str(rows[0]["release"]["name"])
    found = _releases(boards)
    replaced = _replaced(found)
    releases = [_release(slug, rows) for slug, rows in sorted(found.items(), key=strength)
                if slug not in replaced]
    named = {}
    for release in releases:
        for name in _names(release["name"]):
            named.setdefault(name, []).append(release)
    others = [held for board, held in boards.items() if board != BOARD]
    for held in others:
        for row in (held or {}).get("rows") or []:
            matched = {release["slug"]: release for name in _board_names(row["model"])
                       for release in named.get(name, [])}
            effort = len(matched) == 1 and _effort(*matched.values(), row["effort"])
            if effort:
                _join(effort["values"], row["values"])
    return releases


def successor(boards, slug):
    """The current release the release `slug`'s chain of `_replaced` ends at, itself when it is
    current; None when the chain ends anywhere else: a slug the board does not list, a
    deprecated release naming no successor, or a loop."""
    releases = _releases(boards)
    end = _end(releases, _replaced(releases), slug)
    return next((release for release in current(boards) if release["slug"] == end), None)
