"""Invented Artificial Analysis and Arena board fixtures shared by black-box models tests."""

import time

NOW = int(time.time())
ENV = {"NO_COLOR": "1", "TZ": "UTC", **{name: "http://127.0.0.1:9" for name in (
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}}
EVALUATIONS = ("aa-briefcase", "frontiercode-2-0")     # each role's cost a task
# Per release and effort: intelligence index, frontier-code and terminal shares, Arena's agent
# share and cost a task; each but Crux 2 with a terminal share, so Crux 2's is missing, and
# every one alike on the rest (`SAME`)
ROWS = [("acme-max-5", "Acme Max 5", "max", 70, 0.80, 0.80, 20.0),
        ("acme-max-5", "Acme Max 5", "high", 65, 0.735, 0.78, 10.0),
        ("acme-mid-5", "Acme Mid 5", "high", 66, 0.77, 0.79, 15.0),
        ("bolt-3", "Bolt 3", "medium", 60, 0.70, 0.78, 3.0),
        ("crux-2", "Crux 2", "low", 50, 0.60, 0.50, 1.0)]
SAME = {"aa.briefcaseBreakdown.overall.elo": 1400, "aa.omniscience": 50,
        "aa.automationBenchPartialScore": 0.5}
# what a board held from another build is asked again for lacking, carried by a retired model
OLD = {"artificialanalysis.ai": "aa.intelligenceIndexCostPerTask.cost.total aa.effort.level",
       "arena.ai": "arena.agent_task_outcome_explicit arena.agent_steerability "
                   "arena.agent_bash_reliability arena.text_factuality.coding "
                   "arena.text_style_control.coding arena.agent.lower95ci"}


def aa(release, name, effort, values, retired=False):
    return {"model": name, "effort": effort, "slug": f"{release}-{effort}", "maker": "Acme",
            "deprecated": retired, "values": values,
            "release": {"slug": release, "name": name, "deprecatedTo": None}}


def boards():
    rows = {board: [{"model": "Old 1", "effort": "high", "values": dict.fromkeys(names.split(), 0)}]
            for board, names in OLD.items()}
    rows["artificialanalysis.ai"] = [aa("old-1", "Old 1", "high", rows["artificialanalysis.ai"][0]
                                        ["values"], retired=True)]
    for release, name, effort, index, share, agent, cost in ROWS:
        rows["artificialanalysis.ai"].append(aa(release, name, effort, {
            **SAME, "aa.intelligenceIndex": index, "aa.frontierCode20": share,
            **({"aa.terminalBench40": share} if name != "Crux 2" else {}),
            **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost for slug in EVALUATIONS}}))
        rows["arena.ai"].append({"model": name, "effort": effort, "values": {"arena.agent": agent}})
    return {board: {"asked_at": NOW, "fetched_at": NOW, "error": None, "build": "", "rows": found}
            for board, found in rows.items()}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]
