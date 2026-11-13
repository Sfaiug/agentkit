"""`r recommended` on `c` names its keys, and ⏎ opens the why of the orchestrator's first
choice, its model at its effort being no row, Crux 2, which no configured model runs, being none.

Black-box: the program `AK_BIN` names in a terminal (tests/fixtures/akterm.py), its harnesses
fakes listing invented models, the boards held as just asked with invented rows and any board
asked a proxy nobody answers; judged by the screen.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

NOW = int(time.time())
ENV = {"NO_COLOR": "1", "TZ": "UTC", **{name: "http://127.0.0.1:9" for name in (
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}}
KEYS = "  ↑↓ role   ⏎ why   ← cheaper   better →   p models   esc back"
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
OLD = {"artificialanalysis.ai": "aa.intelligenceIndexCostPerTask.cost.total",
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


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsAnswer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")
        akconfig.write(home, {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
                              "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}})
        home.write(".agentkit/state/boards.json", boards())

    def models(self):
        """`r` on `c` in a window of its own, once the answer is drawn."""
        term = Terminal(self.home, size=(100, 60), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        return term, lines(term.wait("comparing all 4 models"))

    def test_enter_opens_the_why_of_the_orchestrators_first_choice(self):
        term, _ = self.models()
        term.keys("Enter")
        term.wait("why Acme Mid 5 high orchestrates")

    def test_the_key_line_names_each_key(self):
        _, shown = self.models()
        self.assertEqual(next(line for line in reversed(shown) if line), KEYS)


if __name__ == "__main__":
    unittest.main()
