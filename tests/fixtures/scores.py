"""Matrix rows worth a chosen quality per role, for the screens' tests: a row is valued on half a
role's measures or more, no other role's, at what is that many points behind a perfect best
(`BEST`), the best the stored matrix keeps, so reading it (`matrix.stored`) scores it so."""

import json

from agentkit import matrix

MEASURES = {"orchestrate": ("arena.agent_task_outcome_explicit", "arena.agent_steerability"),
            "execute": ("livebench.coding", "arena.agent_bash_reliability", "aa.terminalBench40"),
            "review": ("livebench.reasoning", "aa.deepsecBench", "aa.omniscienceHallucinationRate")}
KINDS = {column: kind for measures in matrix.ROLES.values() for column, kind, _ in measures}
PERFECT = {"percent": 100, "share": 1, "mistakes": 0}
BEST = {column: PERFECT[KINDS[column]] for columns in MEASURES.values() for column in columns}


def values(**worth):
    """The values scoring `worth[role]` in each role it names."""
    found = {}
    for role, points in worth.items():
        for column in MEASURES[role]:
            kind = KINDS[column]
            found[column] = (points if kind == "percent" else points / 100 if kind == "share"
                             else (100 - points) / 100)
    return found


def store(rows):
    """`rows` as the stored matrix, with `BEST` as its boards' bests."""
    matrix.cache_path().parent.mkdir(parents=True, exist_ok=True)
    matrix.cache_path().write_text(json.dumps({"matrix": {"computed_at": 1, "config": [],
                                                          "best": BEST, "rows": rows}}))
