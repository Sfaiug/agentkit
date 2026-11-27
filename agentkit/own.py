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

from fractions import Fraction
import math
import re

from . import config, menu, terminal, usage
from .ledger import HOURS, ROLES, recorded

FEW = 20        # a row or the team of fewer tasks says only how many: a few tasks say nothing yet
WORDS = {"orchestrator": "ORCHESTRATOR", "executor": "BUILDER", "reviewer": "REVIEWER"}
DOING = {"orchestrator": "orchestrating", "executor": "building", "reviewer": "reviewing"}
NO_WORK = {"turns": 0, "turn_seconds": None, "checks": 0, "gaps": 0}


def share(part, whole):
    """A row's `part` of its `whole` as a whole percent, `-` where it counts none."""
    return lambda row, _: f"{round(100 * row[part] / row[whole])}%" if row[whole] else "-"


def per_task(part):
    """A row's `part` per task, to a tenth."""
    return lambda row, _: f"{row[part] / row['tasks']:.1f}"


def answers_in(row, _):
    """Median turn time of an orchestrator row: `69 s` below two minutes, `4.2 min` from there,
    `1.5 h` from an hour; `-` below FEW turns."""
    seconds = row["turn_seconds"]
    if row["turns"] < FEW or seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "-"
    if seconds < 120:
        return f"{round(seconds)} s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


def left_out(row, _):
    """Asks a row's done checks found missing, per check, to a tenth; `-` below FEW checks."""
    return fixed(Fraction(row["gaps"], row["checks"]), 1) if row["checks"] >= FEW else "-"


def last(role):
    """The columns every table ends in, none said of a row none of whose tasks went live: the
    hours per task live, then what its model took of its plans in `role` (`took`)."""
    return {"time": lambda row, _: per_live(row) if row["live"] else "",
            "usage": lambda row, paid: took(row, role, paid) if row["live"] else ""}


# Each role's table: each column its heading and its text of a row of FEW tasks or more at what
# its plans cost (`money.month`'s), "" where it says nothing; each role serves its own purpose
# (the owner, 24 Nov 2026: "for exec how fast and it goes through without any extra findings and
# rounds, and for reviwer the more issues it finds the better, I guess also issues which we act
# on"; "For orch I think it really mostly is just subjective feeling and how long it takes").
LEAD = {"tasks": lambda row, _: str(row["tasks"]), "went live": share("live", "tasks")}
COLUMNS = {"orchestrator": {**LEAD, "answers in": answers_in, "left out": left_out,
                            **last("orchestrator")},
           "executor": {**LEAD, "passed 1st review": share("first_pass", "tasks"),
                        "reviews": per_task("reviews"), **last("executor")},
           "reviewer": {**LEAD, "issues": per_task("issues"),
                        "false alarms": share("taken_back", "issues"), **last("reviewer")}}
# What COLUMNS' short headings count, said once under the tables, set apart as parts of a line
# are (terminal.separator)
NOTE = ["answers in: half its turns take no longer",
        "left out: what you asked for that a finished job lacked, per check",
        "reviews and issues: per task",
        "time and usage: per task that went live, "
        "usage also as a share of one login's week on its plan"]


def by_role(teams, now, seats=()):
    """{"team", "orchestrator", "executor", "reviewer"} off the ledger's `teams`, the team now
    `now`, {role: [(name, effort or None)]} in the order held, and `seats`, `ledger.counted`'s
    per-seat counts.  `team` sums the teams all three of whose roles are the team now's; a role's
    rows {"name", "effort", "in_use", "tasks", "live", "first_pass", "reviews", "issues",
    "disputed", "taken_back", "hours", "usage"} sum the teams their model at their effort (None
    where not recorded) did that role in, each orchestrator row also carrying its `turns`,
    `turn_seconds`, `checks` and `gaps` from `seats`, each held model with its row at its effort
    now, in use where that effort is recorded: those in use first, in the order held, then most
    tasks, name and effort, None last."""
    def ours(team, role):
        did = team[role]
        return any(did["name"] == name and recorded(did["effort"]) in (None, effort)
                   for name, effort in now[role])

    def usage_of(found):
        out = {role: {"points": {}, "unrated": 0} for role in ROLES}
        for team in found:
            for role, used in team["usage"].items():
                to = out[role]
                to["unrated"] += used["unrated"]
                for provider, plans in used["points"].items():
                    for plan, value in plans.items():
                        if value:
                            kept = to["points"].setdefault(provider, {})
                            kept[plan] = kept.get(plan, Fraction(0)) + value
        return out

    def summed(found):
        return {**{key: sum(team[key] for team in found)
                   for key in ("tasks", "live", "first_pass", "reviews", "issues",
                               "disputed", "taken_back")},
                "hours": {part: math.fsum(team["hours"][part] for team in found)
                          for part in HOURS},
                "usage": usage_of(found)}
    by_seat = {(seat["name"], seat["effort"]): {key: seat[key] for key in NO_WORK}
               for seat in seats}
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
                      **summed(found),
                      **(by_seat.get(one, NO_WORK) if role == "orchestrator" else {})}
                for one, found in did.items()}
        own[role] = [*(rows.pop(one) for one in in_use), *sorted(rows.values(), key=lambda row: (
            -row["tasks"], row["name"], row["effort"] is None, row["effort"] or ""))]
    return own


def lines(own, cfg, room, paid):
    """`own` (`by_role`) as `ak models` draws it on `room` cells, its plans costing what `paid`
    (`money.month`'s) says: a line on the team now (`spent` among its clauses), then a table a
    role of its rows in `own`'s order under its role's COLUMNS, each in use marked as
    docs/cli-design.md marks one (menu.config_audit's `●` for the one orchestrator, `■` for any of
    several), named as every screen names it (`named`), and under the last table a muted line
    saying what the short headings count.  The name and LEAD's columns are sized once for the
    three tables, to stand under each other, each other column for its own; where a table passes
    the edge every row folds, no column headed: its model's line, then its numbers indented, each
    after its column's name, wrapped between two of them."""
    team, tasks = own["team"], own["team"]["tasks"]
    said = [f"{team['live']} of {tasks} tasks went live", *(
        [f"{per_live(team)} per task live", f"{per_live(team, ['waiting'])} of it waiting",
         *spent(team, paid)] if team["live"] else [])] if tasks >= FEW else [
        f"{tasks} task{'s' * (tasks > 1)}"]
    # a line too wide breaks between its clauses, each ending in `,` or `:`
    shown = menu.packed(re.split(r"(?<=[,:]) ", f"Your team now: {', '.join(said)}")
                        if tasks else ["Your team now has no task yet"], " ", room)
    marks = ("●○", "■□") if terminal.utf8() else ("*.", "#-")
    tables = {role: [((marks[role != "orchestrator"][0], "accent") if row["in_use"] else
                      (marks[role != "orchestrator"][1], "dim"), named(cfg, row),
                      numbers(row, COLUMNS[role], paid)) for row in own[role]] for role in ROLES}
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
    shown += ["", *(terminal.styled(line, "muted")
                    for line in menu.packed(NOTE, terminal.separator(), room))]
    return shown


def per_live(counts, parts=HOURS):
    """`2.7 h`: the hours a row's or the team's tasks spent on `parts` per task that went live."""
    return f"{math.fsum(counts['hours'][part] for part in parts) / counts['live']:.1f} h"


def spent(team, paid):
    """[`$0.60 per task live: orchestrating $0.20, building $0.27, reviewing $0.13`]: what the
    team's tasks took per task live in each role that took points, to the cent as a row's usage
    cell says it (`took`), after their sum; none where they took none or a plan they took points
    of has no price at `paid`, as a sum of some roles would read as all."""
    if took(team, ROLES, paid, share=False) == "-":
        return []
    each = {DOING[role]: Fraction(round(100 * cost(plans, team["live"])), 100)
            for role in ROLES if (plans := priced(team, role, paid))}
    return [f"{money(sum(each.values()), paid)} per task live: " + ", ".join(
        f"{doing} {money(value, paid)}" for doing, value in each.items())]


def took(row, role, paid, *, per=None, share=True):
    """`$0.25 · 0.6%` (or `$0.25` with `share=False`): what `row` took of its plans in `role`
    (one role or several, `priced`) per `per` (`row["live"]` when omitted) in money (`cost`);
    with `share`, the points summed beside it (100 one login's week on a plan), and the share
    alone where a plan has no price, else `-` there; `-` where it took no points; `""` where it
    would divide by zero: each from its exact value (`fixed`)."""
    plans = priced(row, role, paid)
    if not plans:
        return "-"
    divisor = row["live"] if per is None else per
    if not share and any(price is None for _, price in plans):
        return "-"
    if divisor <= 0:
        return ""
    said = f"{fixed(sum(points for points, _ in plans) / divisor, 1)}%" if share else None
    if any(price is None for _, price in plans):
        return said
    text = money(cost(plans, divisor), paid)
    return f"{text}{terminal.separator()}{said}" if share else text


def priced(row, role, paid):
    """[(points, price or None)]: each plan `row` took points of in `role` (one role or several),
    at its price a month in `paid` (`money.month`'s)."""
    roles = (role,) if isinstance(role, str) else role
    return [(points, paid["month"].get(provider, {}).get(plan))
            for one in roles
            for provider, plans in row["usage"][one]["points"].items()
            for plan, points in plans.items()]


def cost(plans, divisor):
    """What `plans` (`priced`, all priced) cost per `divisor`, exactly: each plan's points (100
    one login's week on it) at its price a month as written, a week 12/52 of a month."""
    return sum(points * Fraction(str(price)) for points, price in plans) / divisor / 100 * 12 / 52


def money(value, paid):
    """`$0.25`: exact `value` to the cent (`fixed`) in `paid`'s currency, without UTF-8 by its ISO
    code as the Money page says it (menu.money_value)."""
    code = paid["currency"]
    return (usage.SIGNS[code] if terminal.utf8() else f"{code} ") + fixed(value, 2)


def fixed(value, places):
    """Exact `value`, never below zero, rounded once to `places` decimals as its digits: no float
    between, as a float's binary value can lie across a decimal boundary (0.35 below it), or a
    large one's neighbours farther apart than a cent."""
    whole, part = divmod(round(value * 10 ** places), 10 ** places)
    return f"{whole}.{part:0{places}d}"


def numbers(row, columns, paid):
    """A row's texts under `columns`, a table of COLUMNS, at `paid`: below FEW tasks, its tasks
    alone."""
    if row["tasks"] < FEW:
        return (str(row["tasks"]), *[""] * (len(columns) - 1))
    return tuple(text(row, paid) for text in columns.values())


def named(cfg, row):
    """A row's model as every screen names it: its full name (config.model_name), by the name its
    runs kept where no longer configured or where that name drawn plain is empty, then its effort,
    `none` being none, each plain on its own (menu.named)."""
    name = config.model_name(cfg, row["name"])
    return menu.named({"name": name if terminal.plain(name) else row["name"],
                       "effort": None if row["effort"] == "none" else row["effort"]})


def told(said, room):
    """A folded row's (column's name, its text) pairs, each text after its name, two cells in and
    as many to a line as fit: the indent gives way before a number is parted from its name, and
    one too wide for the screen goes on at its words on lines of its own, two in, the indent
    giving way before a word that fits the screen is cut, never past `room`."""
    lines, joins = [], False    # whether the last line takes another pair
    for head, text in said:
        part = f"{terminal.styled(head, 'muted')} {text}"
        if not text:
            continue
        if joins and terminal.cells(f"{lines[-1]}  {part}") <= room:
            lines[-1] += "  " + part
        elif terminal.cells(part) <= room:
            lines.append(" " * min(2, room - terminal.cells(part)) + part)
            joins = lines[-1].startswith("  ")
        else:
            widest = max((terminal.cells(word) for word in part.split()
                          if terminal.cells(word) <= room), default=0)
            lead = " " * min(2, room - widest)
            lines += [lead + line for line in terminal.wrap(part, room - len(lead))]
            joins = False
    return lines


def hung(text, room):
    """`text` on lines of `room` cells, those after the first two in where each word fits there:
    a word that fits the screen is never cut (docs/cli-design.md)."""
    first, *rest = terminal.wrap(text, room)
    lead = "  " if all(terminal.cells(word) <= room - 2 for word in text.split()) else ""
    return [first, *(lead + line for line in terminal.wrap(" ".join(rest), room - len(lead)))]
