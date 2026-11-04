"""Hide cell layout, one-mark-per-cell resolution, tick choice and label placement.

draw takes (cost, quality, label, mark) points and a two-point comparison line;
it returns styled terminal lines, without knowing models, roles or recommendations.
"""

import math

from . import terminal


def draw(points, baseline, unit, width):
    if width < 60 or not points:
        return []
    high, low = max(p[1] for p in points), min(p[1] for p in points)
    margin = max(len(f"{q:.1f}") for q in (high, low)) + 3
    size, height = min(width, 120) - margin - 1, 8
    end = max(p[0] for p in points) * 1.05 or 1
    grid = [["│"] + [" "] * size for _ in range(height)]

    def x(cost):
        return round(size * cost / end)

    def y(score):
        return 1 + round((height - 3) * (high - score) / (high - low)) if high != low else 4

    placed = [(x(cost), y(score), label, mark) for cost, score, label, mark in sorted(points)]
    front = [p for p in placed if p[3] in ("●", "★")]
    for (ax, ay, *_), (bx, by, *_) in zip(front, front[1:]):
        for xx in range(ax, bx + 1):
            grid[ay][xx] = "─"
        for yy in range(min(ay, by), max(ay, by) + 1):
            grid[yy][bx] = "│"
        grid[ay][bx] = "┘"
    # The reference can start below the displayed quality window; clip it, never rescale it.
    (ac, aq), (bc, bq) = baseline
    if bc > ac:
        for xx in range(max(0, x(ac)), min(size, x(bc)) + 1):
            score = aq + (bq - aq) * (end * xx / size - ac) / (bc - ac)
            if low <= score <= high:
                grid[y(score)][xx] = "┄"
    for xx, yy, _, mark in sorted(placed, key=lambda p: (p[3] == "★", p[3] == "●")):
        grid[yy][xx] = mark
    for xx, yy, label, mark in sorted(placed, key=lambda p: p[3] != "★"):
        if mark == "·":
            continue
        cells = [cell for letter in terminal.cell_texts(terminal.plain(label))
                 for cell in [letter] + [""] * (terminal.cells(letter) - 1)]
        # Try nearby blank runs first. Labels never erase marks, lines or other labels.
        slots = ((4 * abs(row - yy) + min(abs(col - xx - 2), abs(col + len(cells) + 1 - xx)), row, col)
                 for row in range(height) for col in range(1, size + 2 - len(cells))
                 if all(c == " " for c in grid[row][col - 1:col + len(cells) + 1]))
        slot = min(slots, default=None)
        if slot:
            _, row, col = slot
            grid[row][col:col + len(cells)] = cells
    lines = ["  quality ↑"]
    for row, cells in enumerate(grid):
        value = f"{high:.1f}" if row == 1 else f"{low:.1f}" if row == height - 2 else ""
        before, star, after = "".join(cells).rstrip().partition("★")
        lines.append(terminal.styled(value.rjust(margin - 1) + " " + before, "dim")
                     + terminal.styled(star, "accent") + terminal.styled(after, "dim"))
    power = 10 ** math.floor(math.log10(end / 5))
    step = next(n * power for n in (1, 2, 5, 10) if n * power >= end / 5)
    axis, ticks = ["└"] + ["─"] * size, [" "] * (size + 1)
    for n in range(math.floor(end / step) + 1):
        at, text = x(n * step), f"{n * step:g}"
        axis[at] = "└" if n == 0 else "┬"
        start = min(max(0, at - len(text) // 2), len(ticks) - len(text))
        ticks[start:start + len(text)] = text
    return lines + [terminal.styled(" " * margin + "".join(row).rstrip(), "dim")
                    for row in (axis, ticks)] + [terminal.styled(f"  cost → {unit}", "dim")]
