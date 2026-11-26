"""Each role's models by the tasks they did with the team now, off the ledger's teams
(`ledger.counted`): `ak models --json`'s `own`, and the lines `ak models` draws of it (`lines`).
It hides which teams a row sums, and when a row says nothing yet.  A ledger team
has a role of the team now's where its model there is one the team now holds for that role, at
the effort held or at none recorded: an effort ak did not record (none, or a blank, as
config.launched_effort reads one) is no other effort.  A role's row is a model at an effort that
did that role in a team whose two other roles are both the team now's, so a builder's numbers
never move with a reviewer no longer used.  The owner, 24 Nov 2026: "I really like the current
combination of models, and I would like to see why, in numbers".
"""

import math

from . import config, menu, terminal
from .ledger import HOURS, ROLES

FEW = 20        # a row of fewer tasks says only how many: a few tasks say nothing yet
WORDS = {"orchestrator": "ORCHESTRATOR", "executor": "BUILDER", "reviewer": "REVIEWER"}


def share(part, whole):
    """A row's `part` of its `whole` as a whole percent, `-` where it counts none."""
    return lambda row: f"{round(100 * row[part] / row[whole])}%" if row[whole] else "-"


def per_task(part):
    """A row's `part` per task, to a tenth."""
    return lambda row: f"{row[part] / row['tasks']:.1f}"


# Each role's table: each column its heading and its text of a row of FEW tasks or more, "" where
# it says nothing; each role serves its own purpose (the owner, 24 Nov 2026: "for exec how fast
# and it goes through without any extra findings and rounds, and for reviwer the more issues it
# finds the better, I guess also issues which we act on").
LEAD = {"tasks": lambda row: str(row["tasks"]), "went live": share("live", "tasks")}
LAST = {"per task live": lambda row: per_live(row) if row["live"] else ""}
COLUMNS = {"orchestrator": {**LEAD, **LAST},
           "executor": {**LEAD, "passed 1st review": share("first_pass", "tasks"),
                        "reviews per task": per_task("reviews"), **LAST},
           "reviewer": {**LEAD, "issues per task": per_task("issues"),
                        "false alarms": share("taken_back", "issues"), **LAST}}


def by_role(teams, now):
    """{"team", "orchestrator", "executor", "reviewer"} off the ledger's `teams` and the team now
    `now`, {role: [(name, effort or None)]} in the order held.  `team` sums the teams all three of
    whose roles are the team now's; a role's rows {"name", "effort", "in_use", "tasks", "live",
    "first_pass", "reviews", "issues", "disputed", "taken_back", "hours"} sum the teams their
    model at their effort (None where not recorded) did that role in, each held model with its
    row at its effort now, in use where that effort is recorded: those in use first, in the order
    held, then most tasks, name and effort, None last."""
    def ours(team, role):
        did = team[role]
        return any(did["name"] == name and recorded(did["effort"]) in (None, effort)
                   for name, effort in now[role])

    def summed(found):
        return {**{key: sum(team[key] for team in found)
                   for key in ("tasks", "live", "first_pass", "reviews", "issues",
                               "disputed", "taken_back")},
                "hours": {part: math.fsum(team["hours"][part] for team in found)
                          for part in HOURS}}
    own = {"team": summed([team for team in teams if all(ours(team, role) for role in ROLES)])}
    for role in ROLES:
        did = {held: [] for held in now[role]}     # {(name, effort): the teams it did role in}
        for team in teams:     # a role no model did, as a run launched from no seat, no row
            if team[role]["name"] is not None and all(ours(team, other) for other in ROLES
                                                      if other != role):
                did.setdefault((team[role]["name"], recorded(team[role]["effort"])),
                               []).append(team)
        in_use = [held for held in now[role] if held[1] is not None]
        rows = {one: {"name": one[0], "effort": one[1], "in_use": one in in_use,
                      **summed(found)} for one, found in did.items()}
        own[role] = [*(rows.pop(one) for one in in_use), *sorted(rows.values(), key=lambda row: (
            -row["tasks"], row["name"], row["effort"] is None, row["effort"] or ""))]
    return own


def recorded(effort):
    """A ledger team's effort, None where it names none or a blank one."""
    return effort if isinstance(effort, str) and effort.strip() else None


def lines(own, cfg, room):
    """`own` (`by_role`) as `ak models` draws it on `room` cells: a line on the team now, then a
    table a role of its rows in `own`'s order under its role's COLUMNS, each in use marked as
    docs/cli-design.md marks one (menu.config_audit's `●` for the one orchestrator, `■` for any
    of several), named as every screen names it (`named`).  The name and LEAD's columns are sized
    once for the three tables, to stand under each other, each other column for its own; where a
    table passes the edge every row folds, no column headed: its model's line, then its numbers
    indented, each after its column's name, wrapped between two of them."""
    team, tasks = own["team"], own["team"]["tasks"]
    said = [f"{team['live']} of {tasks} tasks went live", *(
        [f"{per_live(team)} per task live", f"{per_live(team, ['waiting'])} of it waiting"]
        if team["live"] else [])] if tasks >= FEW else [f"{tasks} task{'s' * (tasks > 1)}"]
    # a line too wide breaks between its clauses
    shown = menu.packed(["Your team now:", *(part + "," for part in said[:-1]), said[-1]]
                        if tasks else ["Your team now has no task yet"], " ", room)
    marks = ("●○", "■□") if terminal.utf8() else ("*.", "#-")
    tables = {role: [((marks[role != "orchestrator"][0], "accent") if row["in_use"] else
                      (marks[role != "orchestrator"][1], "dim"), named(cfg, row),
                      numbers(row, COLUMNS[role])) for row in own[role]] for role in ROLES}
    # each table's widths, its names' first; the names' and LEAD's then the widest of the three
    widths = {role: [max(map(terminal.cells, column)) for column in zip(
        (WORDS[role], *COLUMNS[role]), *((f"{mark} {model}", *texts)
                                         for (mark, _), model, texts in rows))]
        for role, rows in tables.items()}
    lead = [max(column) for column in zip(*widths.values())][:1 + len(LEAD)]
    widths = {role: [*lead, *sized[len(lead):]] for role, sized in widths.items()}
    folded = any(sum(sized) + 2 * (len(sized) - 1) > room for sized in widths.values())

    def columns(texts, sized):
        return "  ".join(terminal.pad(text, column, right=True)
                         for text, column in zip(texts, sized)).rstrip()
    for role, rows in tables.items():
        word, (name, *sized) = terminal.styled(WORDS[role], "bold"), widths[role]
        shown += ["", word] if folded else ["", word + " " * (
            name + 2 - terminal.cells(WORDS[role])) + terminal.styled(
                columns(COLUMNS[role], sized), "muted")]
        for (mark, kind), model, texts in rows:
            if folded:
                first, *rest = hung(f"{mark} {model}", room)
                rest += told(zip(COLUMNS[role], texts), room)
            else:
                first, rest = f"{mark} {terminal.pad(model, name - 2)}  {columns(texts, sized)}", []
            shown += [terminal.styled(mark, kind) + first[len(mark):], *rest]
    return shown


def per_live(counts, parts=HOURS):
    """`2.7 h`: the hours a row's or the team's tasks spent on `parts` per task that went live."""
    return f"{math.fsum(counts['hours'][part] for part in parts) / counts['live']:.1f} h"


def numbers(row, columns):
    """A row's texts under `columns`, a table of COLUMNS: below FEW tasks, its tasks alone."""
    if row["tasks"] < FEW:
        return (str(row["tasks"]), *[""] * (len(columns) - 1))
    return tuple(text(row) for text in columns.values())


def named(cfg, row):
    """A row's model as the role lines over the boards name it (menu.models_said): its full name
    (config.model_name), by the name its runs kept where no longer configured or where that name
    drawn plain is empty, then its effort, `none` being none, each plain on its own (menu.named)."""
    name = config.model_name(cfg, row["name"])
    return menu.named({"name": name if terminal.plain(name) else row["name"],
                       "effort": None if row["effort"] == "none" else row["effort"]})


def told(said, room):
    """A folded row's (column's name, its text) pairs, each text after its name, two cells in and
    as many to a line as fit: the indent gives way before a number is parted from its name, and
    one too wide for the screen wraps at its words, never past `room`."""
    lines = []
    for head, text in said:
        part = f"{terminal.styled(head, 'muted')} {text}"
        if not text:
            continue
        if lines and lines[-1].startswith("  ") and terminal.cells(f"{lines[-1]}  {part}") <= room:
            lines[-1] += "  " + part
        else:
            lead = " " * max(0, min(2, room - terminal.cells(part)))
            lines += [lead + line for line in menu.packed([part], "", room)]
    return lines


def hung(text, room):
    """`text` on lines of `room` cells, those after the first two in where each word fits there:
    a word that fits the screen is never cut (docs/cli-design.md)."""
    first, *rest = terminal.wrap(text, room)
    lead = "  " if all(terminal.cells(word) <= room - 2 for word in text.split()) else ""
    return [first, *(lead + line for line in terminal.wrap(" ".join(rest), room - len(lead)))]
