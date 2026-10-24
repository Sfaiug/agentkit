"""Matrix rows worth a chosen quality per role, for the screens' tests: a row is valued on half a
role's measures or more, no other role's, at what is that many points behind a perfect best
(`BEST`), the best the stored matrix keeps, so reading it (`matrix.stored`) scores it so."""

import json
from unittest.mock import patch

from agentkit import matrix, menu

MEASURES = {"orchestrate": ("arena.agent_task_outcome_explicit", "arena.agent_steerability"),
            "execute": ("livebench.coding", "arena.agent_bash_reliability", "aa.terminalBench40"),
            "review": ("livebench.reasoning", "aa.deepsecBench", "aa.omniscience")}
KINDS = {column: kind for measures in matrix.ROLES.values() for column, kind, _ in measures}
PERFECT = {"percent": 100, "share": 1}
BEST = {column: {"best": PERFECT[KINDS[column]], "typical": 0}
        for columns in MEASURES.values() for column in columns}


def values(**worth):
    """The values scoring `worth[role]` in each role it names."""
    found = {}
    for role, points in worth.items():
        for column in MEASURES[role]:
            kind = KINDS[column]
            found[column] = points if kind == "percent" else points / 100
    return found


def store(rows):
    """`rows` as the stored matrix, with `BEST` as its boards' bests."""
    matrix.cache_path().parent.mkdir(parents=True, exist_ok=True)
    matrix.cache_path().write_text(json.dumps({"matrix": {"computed_at": 1, "config": [],
                                                          "bests": BEST, "rows": rows}}))


class Landed(menu.Fetch):
    """The models screen's reading of the boards, landed before it draws."""

    def __init__(self, work):
        super().__init__(work)
        self.join()


def read_as_stored(stack):
    """The models screen's reading of the boards (matrix.refresh) landed before it draws and
    leaving the stored matrix as it stands: no board is asked."""
    stack.enter_context(patch.object(matrix, "refresh", side_effect=lambda cfg, **_kw: (
        {}, matrix.stored().get("rows") or [])))
    stack.enter_context(patch.object(menu, "Fetch", Landed))
