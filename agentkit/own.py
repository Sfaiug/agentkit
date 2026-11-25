"""Each role's models by the tasks they did with the team now, off the ledger's teams
(`ledger.by_team`): `ak models --json`'s `own`.  It hides which teams a row sums.  A ledger team
has a role of the team now's where its model there is one the team now holds for that role, at
the effort held or at none recorded: an effort ak did not record (none, or a blank, as
config.launched_effort reads one) is no other effort.  A role's row is a model at an effort that
did that role in a team whose two other roles are both the team now's, so a builder's numbers
never move with a reviewer no longer used.  The owner, 24 Nov 2026: "I really like the current
combination of models, and I would like to see why, in numbers".
"""

import math

from .ledger import HOURS, ROLES


def by_role(teams, now):
    """{"team", "orchestrator", "executor", "reviewer"} off the ledger's `teams` and the team now
    `now`, {role: [(name, effort or None)]} in the order held.  `team` sums the teams all three of
    whose roles are the team now's; a role's rows {"name", "effort", "in_use", "tasks", "live",
    "hours"} sum the teams their model at their effort (None where not recorded) did that role
    in, each held model with its row at its effort now, in use where that effort is recorded:
    those in use first, in the order held, then most tasks, name and effort, None last."""
    def ours(team, role):
        did = team[role]
        return any(did["name"] == name and recorded(did["effort"]) in (None, effort)
                   for name, effort in now[role])

    def summed(found):
        return {"tasks": sum(team["tasks"] for team in found),
                "live": sum(team["live"] for team in found),
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
