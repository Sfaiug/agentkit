"""↑/↓ on the models screen move a pointer over the rows its answer shows, from the first role's
pick; a knob step keeps it on its row while that row is shown, else puts it on its role's pick.
⏎ opens the pointed row's why: its quality and cost, how far behind the role's best it is, each
measure's points behind and how it was got, and the rows the boards cannot tell from it; Esc
returns with the pointer where it was.  On 40 cells each measure's how takes a line under it.

Black-box, as tests/test_key_models_answer.py: the program `AK_BIN` names in a terminal, its
harnesses fakes listing invented models, the boards held as just asked with invented rows;
judged by the screen.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, EVALUATIONS, NOW, OLD, aa, lines

# Per release and effort: intelligence index, frontier-code and terminal shares, DeepSec Bench,
# documents passing every check, Omniscience, cost a task and Arena's agent share and webdev,
# none for Acme Max 5 high (carried from max) and Crux 2 (estimated, or no score where too few
# rows have every measure); AA-LCR on Acme Max 5 max alone, so the rest have none or carry it
ROWS = [("acme-max-5", "Acme Max 5", "max", 70, 0.80, 0.60, 0.90, 50, 20.0, (0.80, 1400)),
        ("acme-max-5", "Acme Max 5", "high", 65, 0.74, 0.62, 0.60, 48, 10.0, None),
        ("acme-mid-5", "Acme Mid 5", "high", 66, 0.77, 0.66, 0.85, 49, 15.0, (0.79, 1380)),
        ("bolt-3", "Bolt 3", "medium", 60, 0.70, 0.70, 0.60, 45, 3.0, (0.78, 1350)),
        ("crux-2", "Crux 2", "low", 50, 0.60, 0.50, 0.50, 30, 1.0, None)]


def boards():
    rows = {board: [{"model": "Old 1", "effort": "high", "values": dict.fromkeys(names.split(), 0)}]
            for board, names in OLD.items()}
    rows["artificialanalysis.ai"] = [aa("old-1", "Old 1", "high", rows["artificialanalysis.ai"][0]
                                        ["values"], retired=True)]
    for release, name, effort, index, share, deepsec, pdf, omni, cost, arena in ROWS:
        rows["artificialanalysis.ai"].append(aa(release, name, effort, {
            "aa.briefcaseBreakdown.overall.elo": 1400, "aa.gdpval": 1400, "aa.omniscience": omni,
            **({"aa.lcr": 0.9} if effort == "max" else {}), "aa.intelligenceIndex": index,
            "aa.frontierCode": share, "aa.terminalBench40": share, "aa.deepsecBench": deepsec,
            "aa.gdpPdfAllPass": pdf,
            **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost for slug in EVALUATIONS}}))
        if arena:
            rows["arena.ai"].append({"model": name, "effort": effort, "values": {
                "arena.agent": arena[0], "arena.webdev": arena[1]}})
    return {board: {"asked_at": NOW, "fetched_at": NOW, "error": None, "build": "", "rows": found}
            for board, found in rows.items()}


ORCH_PICK = "›   Bolt 3 medium         98.2   $3.00  ★ pick"
CRUX_ORCH = ["  why Crux 2 low orchestrates",
             "  quality 93.3 ± 0.0   $1.00 a AA-Briefcase task",
             "  6.7 behind the best, Acme Max 5 max",
             "",
             "                  behind the best",
             "  AA-Briefcase                0.0  measured, 1400",
             "  GDPval-AA                   0.0  measured, 1400",
             "  Arena Agent                      no score",
             "  AA-Omniscience             20.0  measured, 30",
             "  AA-LCR                           no score",
             "",
             "  no tie: the boards tell it from every other row",
             "",
             "  esc back"]
MAX_HIGH_BUILDS = ["  why Acme Max 5 high builds",
                   "  quality 94.3 ± 2.3   $10.00 a Terminal-Bench 4.0 task",
                   "  5.7 behind the best, Acme Max 5 max",
                   "",
                   "                      behind the best",
                   "  FrontierCode                    6.0  measured, 74.0%",
                   "  Terminal-Bench 4.0              6.0  measured, 74.0%",
                   "  Arena WebDev                    5.0  carried from max",
                   "",
                   "  ≈ tie with 2 rows, among them:",
                   "    Acme Mid 5 high · Bolt 3 medium"]
CRUX_BUILDS_40 = ["  why Crux 2 low builds",
                  "  quality 80.0 ± 2.6",
                  "  $1.00 a Terminal-Bench 4.0 task",
                  "  20.0 behind the best, Acme Max 5 max",
                  "",
                  "                      behind the best",
                  "  FrontierCode                   20.0",
                  "    measured, 60.0%",
                  "  Terminal-Bench 4.0             20.0",
                  "    measured, 60.0%",
                  "  Arena WebDev                   20.1",
                  "    estimated, counted 1.1 low",
                  "",
                  "  no tie: the boards tell it from every",
                  "  other row"]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsWhy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")

    def setUp(self):
        akconfig.write(self.home, {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
                                   "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}})
        self.home.write(".agentkit/state/boards.json", boards())

    def models(self, width=78):
        """`r` on `c` in a window of its own, once the answer is drawn."""
        term = Terminal(self.home, size=(width, 60), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        return term, lines(term.wait("comparing all 4 models"))

    def why(self, term, *keys):
        term.keys(*keys, "Enter")
        shown = lines(term.wait(lambda screen: "\n  why " in screen))     # the key line has `⏎ why`
        return shown[shown.index(next(line for line in shown if line.startswith("  why "))):]

    def test_the_pointer_keeps_its_row_through_a_knob_step_or_goes_to_its_pick(self):
        term, shown = self.models()
        self.assertIn(ORCH_PICK, shown)
        term.keys("Right")              # within 6: the orchestrator's front stands as it was
        shown = lines(term.wait("within ‹ 6 ›"))
        self.assertIn(ORCH_PICK, shown)
        self.assertIn("    Crux 2 low            80.0   $1.00  1 estimated", shown)
        term.keys("Up", "Up")
        term.wait("›   Acme Max 5 max       100.0  $20.00  no harness")
        term.keys("Right")              # within 7: Acme Max 5 max leaves the orchestrator's line
        shown = lines(term.wait("within ‹ 7 ›"))
        self.assertIn("›   Crux 2 low            93.3   $1.00  ★ pick", shown)
        self.assertEqual(sum(line.startswith("›") for line in shown), 1)

    def test_enter_says_where_a_rows_quality_comes_from_and_esc_returns(self):
        term, _ = self.models()
        self.assertEqual(self.why(term, "Down")[:len(CRUX_ORCH)], CRUX_ORCH)
        term.keys("Escape")
        shown = lines(term.wait("comparing all 4 models"))
        self.assertIn("›   Crux 2 low            93.3   $1.00", shown)
        self.assertEqual(self.why(term, "Down", "Down", "Down")[:len(MAX_HIGH_BUILDS)],
                         MAX_HIGH_BUILDS)

    def test_on_40_cells_each_measures_how_takes_a_line_under_it(self):
        term, _ = self.models(40)
        term.keys("Right")
        term.wait("‹ 6 ›")
        self.assertEqual(self.why(term, *["Down"] * 6)[:len(CRUX_BUILDS_40)], CRUX_BUILDS_40)


if __name__ == "__main__":
    unittest.main()
