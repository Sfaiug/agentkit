"""The tables `config · limits` draws of what your tasks took (`ledger.counted`'s rows), the
owner's asks of 24 Nov 2026: under `executor_lines` by size (`lines`), under `rescope_findings`
by the issues their first review found (`issues`).  Each is its rows, columns of hours and mark
given to one drawing, rather than a module of its own writing the fold and the usage cell again:
each number written once, then fixed columns where every row fits the page, else every row folded
with its numbers named, so no width loses or rewrites a number another width shows.
"""

from fractions import Fraction
import math

from . import ledger, own, terminal

FEW = 20        # a row of fewer tasks shows its tasks alone: a few tasks say nothing yet
# each table's columns of hours, and the parts of `ledger.HOURS` each sums
BY_SIZE = {"building": ("build",), "reviewing": ("review",), "own tests": ("checks",),
           "waiting": ("waiting",)}
BY_ISSUES = {"time": tuple(ledger.HOURS)}


def lines(sizes, limit, width, paid):
    """`sizes` at `executor_lines` `limit` (`_drawn`): a row of each size, smallest first, its
    numbers for every 100 lines live, marked `over` wholly above a limit on."""
    dash = "–" if terminal.utf8() else "-"
    rows = []
    for row in sorted(sizes, key=lambda row: row["upto"]):
        low = row["upto"] - ledger.SIZE + 1
        rows.append((f"{low}{dash}{row['upto']}", row, Fraction(row["lines_live"], 100),
                     "over" if type(limit) is int and 0 < limit < low else ""))
    return _drawn("What your tasks of each size took, for every 100 lines that went live",
                  "lines", BY_SIZE, rows, width, paid)


def issues(first_issues, limit, width, paid):
    """`first_issues` at `rescope_findings` `limit` (`_drawn`): a row of each number of issues,
    fewest first, its numbers for every task live, marked `ends the run` at or above a limit
    on."""
    rows = [(str(row["issues"]), row, row["live"],
             "ends the run" if 0 < limit <= row["issues"] else "")
            for row in sorted(first_issues, key=lambda row: row["issues"])]
    return _drawn("What your tasks took, by the issues their first review found", "issues",
                  BY_ISSUES, rows, width, paid)


def _drawn(heading, name, hours, rows, width, paid):
    """The lines of `rows`, each `(label, row, per, mark)`, at `paid` (`money.month`'s) held on
    `width` cells: `heading`, ending `· none yet` with no row, then a row of each under its
    `name`, its numbers for every `per` (`_shown`), as fixed columns with two-space gutters where
    every row fits, else each folded: its label, tasks and mark, then, indented, each number it
    shows after its column's name."""
    tail = "last 30 days" if rows else "none yet"
    head = ["", *(f"  {part}" for part in terminal.wrap(f"{heading} · {tail}", width - 2))]
    if not rows:
        return head
    columns = (name, "tasks", "went live", *hours, "usage")
    rows = [(label, row["tasks"], _shown(row, per, hours, paid), mark)
            for label, row, per, mark in rows]
    marked = any(mark for *_, mark in rows)
    grid = [[*columns, *[""] * marked],
            *([label, str(tasks), *(shown.get(col, "") for col in columns[2:]),
               *[mark] * marked] for label, tasks, shown, mark in rows)]
    wide = [max(map(terminal.cells, column)) for column in zip(*grid)]
    table = [("  " + "  ".join(f"{cell:<{size}}" if at in (0, len(columns)) else f"{cell:>{size}}"
                               for at, (cell, size) in enumerate(zip(cells, wide)))).rstrip()
             for cells in grid]
    if max(map(terminal.cells, table)) <= width:
        return [*head, "", terminal.styled(table[0], "muted"), *table[1:]]
    folded = []
    for label, tasks, shown, mark in rows:
        folded += [*_packed([label, f"{tasks} task{'s' * (tasks != 1)}", *[mark] * bool(mark)],
                            "  ", width),
                   *_packed([f"{col} {text}" for col, text in shown.items()], "    ", width)]
    return [*head, "", *folded]


def _shown(row, per, hours, paid):
    """The numbers `row` shows, by column, each written once: none for a few tasks or an hour no
    finite number of zero or more; else the share that went live, a whole percent, with `per`
    above zero each of `hours`' columns its parts' hours for every `per`, the exact quotient
    rounded half to even to a tenth and in plain digits whatever its size, and what its tasks
    took in all three roles together for every `per` as money (`own.took`), `-` with no points
    or an unpriced plan."""
    if row["tasks"] < FEW or not all(math.isfinite(hour) and hour >= 0
                                     for hour in row["hours"].values()):
        return {}
    shown = {"went live": f"{round(100 * row['live'] / row['tasks'])}%"}
    if per > 0:
        for col, parts in hours.items():
            tenths = round(sum(Fraction(row["hours"][part]) for part in parts) * 10 / per)
            shown[col] = f"{tenths // 10}.{tenths % 10} h"
    if cell := own.took(row, ledger.ROLES, paid, per=per, share=False):
        shown["usage"] = cell
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
