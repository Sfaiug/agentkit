"""What your tasks of each size took (`ledger.counted`'s `sizes`), drawn under `executor_lines`
on `config · limits`: the owner's ask of 24 Nov 2026.  It hides how a size's row is drawn: each
number written once, then fixed columns where every row fits the page, else every row folded
with its numbers named, so no width loses or rewrites a number another width shows.
"""

from fractions import Fraction
import math

from . import ledger, own, terminal

HEADING = "What your tasks of each size took, for every 100 lines that went live"
FEW = 20        # a row of fewer tasks shows its tasks alone: a few tasks say nothing yet
PARTS = {"building": "build", "reviewing": "review", "own tests": "checks", "waiting": "waiting"}
COLUMNS = ("lines", "tasks", "went live", *PARTS, "usage")


def lines(sizes, limit, width, paid):
    """The lines of `sizes` at `limit` and `paid` (`money.month`'s) held on `width` cells: the
    heading, ending `· none yet` with no row, then a row of each size, smallest first, marked
    `over` wholly above a limit on, as fixed columns with two-space gutters where every row fits,
    else each folded: its lines, tasks and mark, then, indented, each number it shows after its
    column's name."""
    tail = "last 30 days" if sizes else "none yet"
    head = ["", *(f"  {part}" for part in terminal.wrap(f"{HEADING} · {tail}", width - 2))]
    if not sizes:
        return head
    dash = "–" if terminal.utf8() else "-"
    rows = []
    for row in sorted(sizes, key=lambda row: row["upto"]):
        low = row["upto"] - ledger.SIZE + 1
        rows.append((f"{low}{dash}{row['upto']}", row["tasks"], _shown(row, paid),
                     "over" if type(limit) is int and 0 < limit < low else ""))
    marked = any(mark for *_, mark in rows)
    grid = [[*COLUMNS, *[""] * marked],
            *([label, str(tasks), *(shown.get(name, "") for name in COLUMNS[2:]),
               *[mark] * marked] for label, tasks, shown, mark in rows)]
    wide = [max(map(terminal.cells, column)) for column in zip(*grid)]
    table = [("  " + "  ".join(f"{cell:<{size}}" if at in (0, len(COLUMNS)) else f"{cell:>{size}}"
                               for at, (cell, size) in enumerate(zip(cells, wide)))).rstrip()
             for cells in grid]
    if max(map(terminal.cells, table)) <= width:
        return [*head, "", terminal.styled(table[0], "muted"), *table[1:]]
    folded = []
    for label, tasks, shown, mark in rows:
        folded += [*_packed([label, f"{tasks} task{'s' * (tasks != 1)}", *[mark] * bool(mark)],
                            "  ", width),
                   *_packed([f"{name} {text}" for name, text in shown.items()], "    ", width)]
    return [*head, "", *folded]


def _shown(row, paid):
    """The numbers `row` shows, by column, each written once: none for a few tasks or an hour no
    finite number of zero or more; else the share that went live, a whole percent, and with a line
    live each part's hours for every 100 lines live, the exact quotient rounded half to even to a
    tenth and in plain digits whatever its size, and what its tasks took in all three roles
    together for every 100 lines live as money (`own.took`), `-` with no points or an unpriced
    plan."""
    hours, live = row["hours"], row["lines_live"]
    if row["tasks"] < FEW or not all(math.isfinite(hour) and hour >= 0 for hour in hours.values()):
        return {}
    shown = {"went live": f"{round(100 * row['live'] / row['tasks'])}%"}
    if live > 0:
        for name, part in PARTS.items():
            tenths = round(Fraction(hours[part]) * 1000 / Fraction(live))
            shown[name] = f"{tenths // 10}.{tenths % 10} h"
        shown["usage"] = own.took(row, ledger.ROLES, paid, per=Fraction(live, 100), share=False)
    return shown


def _packed(items, lead, width):
    """`items` after `lead` on lines of `width` cells, two spaces apart and wrapping between two;
    one wider than its room cut as terminal.wrap cuts."""
    room, packed = max(1, width - len(lead)), []
    for item in items:
        if packed and terminal.cells(packed[-1]) + 2 + terminal.cells(item) <= room:
            packed[-1] += f"  {item}"
        else:
            packed += [item] if terminal.cells(item) <= room else terminal.wrap(item, room)
    return [f"{lead}{line}".rstrip() for line in packed]
