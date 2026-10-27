"""`r recommended` on `c` answers each role over every current model on the boards: its best,
then its line of best quality for the money around the pick, each row's notes, and under a pick
no harness of yours runs what `r` takes, the pointer on the first role's pick.  ←/→ step `within` and the answer follows; on 40 cells
each row's numbers take a line under its name.  `r` takes each role's take at its effort: into
new seats' [defaults] in a window of its own, and into a seat's record alone, its orchestrator
only said, over a seat; a save that fails changes nothing and says why.

Black-box: the program `AK_BIN` names in a terminal (tests/fixtures/akterm.py), its harnesses
fakes listing invented models, the boards held as just asked with invented rows and any board
asked a proxy nobody answers; judged by the screen and config.toml.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

NOW = int(time.time())
ENV = {"NO_COLOR": "1", "TZ": "UTC", **{name: "http://127.0.0.1:9" for name in (
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}}
KEYS = "  ↑↓ move   ←→ points   ⏎ why   r take   esc back"
EVALUATIONS = ("aa-briefcase", "terminalbench-4-0", "gdp-pdf")     # each role's cost a task
# Per release and effort: intelligence index, frontier-code and terminal shares, DeepSec Bench,
# documents passing every check, Arena's agent share and cost a task; each but Crux 2 at Arena's
# best webdev, so Crux 2's is estimated, and every one alike on the rest (`SAME`)
ROWS = [("acme-max-5", "Acme Max 5", "max", 70, 0.80, 0.60, 0.9, 0.80, 20.0),
        ("acme-max-5", "Acme Max 5", "high", 65, 0.7325, 0.62, 0.6, 0.78, 10.0),
        ("acme-mid-5", "Acme Mid 5", "high", 66, 0.77, 0.66, 0.9, 0.79, 15.0),
        ("bolt-3", "Bolt 3", "medium", 60, 0.70, 0.70, 0.6, 0.78, 3.0),
        ("crux-2", "Crux 2", "low", 50, 0.60, 0.50, 0.5, 0.50, 1.0)]
SAME = {"aa.briefcaseBreakdown.overall.elo": 1400, "aa.gdpval": 1400, "aa.omniscience": 50,
        "aa.lcr": 0.9}
# what a board held from another build is asked again for lacking, carried by a retired model
OLD = {"artificialanalysis.ai": "aa.intelligenceIndexCostPerTask.cost.total",
       "arena.ai": "arena.agent_task_outcome_explicit arena.agent_steerability "
                   "arena.agent_bash_reliability arena.text_factuality.coding "
                   "arena.text_style_control.coding arena.agent.lower95ci",
       "livebench.ai": "livebench.long_agentic livebench.coding livebench.reasoning "
                       "livebench.cost_coding"}

def aa(release, name, effort, values, retired=False):
    return {"model": name, "effort": effort, "slug": f"{release}-{effort}", "maker": "Acme",
            "deprecated": retired, "values": values,
            "release": {"slug": release, "name": name, "deprecatedTo": None}}


def boards():
    rows = {board: [{"model": "Old 1", "effort": "high", "values": dict.fromkeys(names.split(), 0)}]
            for board, names in OLD.items()}
    rows["artificialanalysis.ai"] = [aa("old-1", "Old 1", "high", rows["artificialanalysis.ai"][0]
                                        ["values"], retired=True)]
    for release, name, effort, index, share, deepsec, pdf, agent, cost in ROWS:
        rows["artificialanalysis.ai"].append(aa(release, name, effort, {
            **SAME, "aa.intelligenceIndex": index, "aa.frontierCode": share,
            "aa.terminalBench40": share, "aa.deepsecBench": deepsec, "aa.gdpPdfAllPass": pdf,
            **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost for slug in EVALUATIONS}}))
        rows["arena.ai"].append({"model": name, "effort": effort, "values": {
            "arena.agent": agent, **({"arena.webdev": 1400} if name != "Crux 2" else {})}})
    return {board: {"asked_at": NOW, "fetched_at": NOW, "error": None, "build": "", "rows": found}
            for board, found in rows.items()}

ORCH = ["  orch · best 100.0    quality  a task",
        "    Acme Max 5 max       100.0  $20.00  ≈ tie · no harness",
        "    Acme Mid 5 high       99.8  $15.00  ≈ tie",
        "    Bolt 3 medium         99.6   $3.00  ★ pick",
        "    Crux 2 low            94.0   $1.00"]
BUILDS = ["  builds · best 100.0  quality  a task",
          "    Acme Max 5 max       100.0  $20.00  ≈ tie · no harness",
          "    Acme Mid 5 high       98.0  $15.00  ≈ tie",
          "    Acme Max 5 high       95.5  $10.00  ★ pick · no harness",
          "      r takes Acme Mid 5 high, 98.0, $15.00",
          "    Bolt 3 medium         93.3   $3.00  ≈ tie",
          "    Crux 2 low            80.6   $1.00  1 estimated"]
REVIEWS = ["  reviews · best 98.6  quality  a task",
           "    Acme Mid 5 high       98.6  $15.00  ★ pick",
           "    Bolt 3 medium         92.0   $3.00",
           "    Crux 2 low            84.0   $1.00"]
LEGEND = ["  as good    within ‹ 5 › points of the best, then the cheapest",
          "  ≈ tie      the boards cannot tell it from ★ pick",
          "  estimated  scores no effort of it has, counted low",
          f"  comparing all 4 models · boards read {time.strftime('%H:%M', time.gmtime(NOW))}"]
SEATS = ("acme-fix", "acme-ask")


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
        cls.config = home.path / ".agentkit/config.toml"
        cls.seats = {name: Seat(home, name, model="mid", record={
            "workers": ["bolt"], "reviewers": ["bolt"]}) for name in SEATS}

    def setUp(self):
        akconfig.write(self.home, {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
                                   "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}})
        self.home.write(".agentkit/state/boards.json", boards())
        for name, seat in self.seats.items():
            self.home.write(f".agentkit/state/session-{name}.json", seat.record)
        self.given = self.config.read_bytes()

    def models(self, width=100, seat=None):
        """`r` on `c`, over `seat` or in a window of its own, once the answer is drawn."""
        term = Terminal(self.home, *(("attach", "--overlay") if seat else ()), size=(width, 60),
                        env={**ENV, **({"AGENTKIT_SESSION": seat} if seat else {})})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        return term, lines(term.wait("comparing all 4 models"))

    def record(self, name):
        return json.loads((self.home.path / f".agentkit/state/session-{name}.json").read_text())

    def kept(self, name):
        """Whether seat `name` runs what it was opened with, each at the entries' efforts."""
        record = self.record(name)
        return ([record[role] for role in ("orchestrator", "workers", "reviewers")]
                == ["mid", ["bolt"], ["bolt"]] and all(
                    efforts == {"effort": "low"} for efforts in record.get("efforts", {}).values()))

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_each_role_is_answered_and_a_knob_step_moves_the_pick(self):
        term, shown = self.models()
        at = shown.index(ORCH[0])
        pointed = [*ORCH[:3], "›" + ORCH[3][1:], *ORCH[4:]]    # the pointer starts on the pick
        self.assertEqual(shown[at:at + 21], [*pointed, *BUILDS, *REVIEWS, "", *LEGEND])
        self.assertEqual(next(line for line in reversed(shown) if line), KEYS)
        term.keys("Left")
        shown = lines(term.wait("within ‹ 4 ›"))
        at = shown.index(BUILDS[0])
        self.assertEqual(shown[at + 2:at + 5], ["    Acme Mid 5 high       98.0  $15.00  ★ pick",
                                                "    Acme Max 5 high       95.5  $10.00  ≈ tie · no harness",
                                                "    Bolt 3 medium         93.3   $3.00  ≈ tie"])
        self.assertEqual(akconfig.read(self.home)["within"], 4)

    def test_r_takes_each_roles_take_at_its_effort(self):
        term, _ = self.models()
        term.keys("r")
        self.until(lambda: akconfig.read(self.home)["defaults"].get("reviewers") == ["mid"],
                   "r never took the answer")
        saved = akconfig.read(self.home)
        self.assertEqual(saved["defaults"], {"orchestrator": "bolt", "workers": ["mid"],
                                             "reviewers": ["mid"]})
        self.assertEqual(saved["models"]["bolt"]["effort"], "medium")
        self.assertEqual({key: saved["models"]["mid"].get(key) for key in (
            "effort", "exec_effort", "review_effort")},
            {"effort": "low", "exec_effort": "high", "review_effort": "high"})
        self.assertTrue(all(self.kept(name) for name in SEATS), "an open seat changed")

    def test_a_config_that_cannot_be_saved_changes_nothing_and_says_why(self):
        # the save's temporary file cannot be written: a directory stands in its place
        blocked = self.home.path / ".agentkit/config.tmp"
        blocked.mkdir()
        self.addCleanup(blocked.rmdir)
        term, _ = self.models()
        term.keys("r")
        term.wait("Is a directory")
        self.assertEqual(self.config.read_bytes(), self.given)

    def test_r_on_a_seat_s_c_takes_the_recommended_efforts_into_its_record_alone(self):
        term, _ = self.models(seat="acme-fix")
        term.keys("r")
        self.until(lambda: self.record("acme-fix")["reviewers"] == ["mid"], "r never took it")
        record = self.record("acme-fix")
        # its orchestrator is only said: moving the seat is its orchestrator mark's
        self.assertEqual((record["orchestrator"], record["workers"]), ("mid", ["mid"]))
        self.assertEqual(record["efforts"]["mid"],
                         {"effort": "low", "exec_effort": "high", "review_effort": "high"})
        self.assertEqual(self.config.read_bytes(), self.given)
        self.assertTrue(self.kept("acme-ask"), "another seat changed")

    def test_efforts_that_cannot_be_saved_change_no_mark(self):
        blocked = self.home.path / ".agentkit/state/session-acme-fix.tmp"
        term, _ = self.models(seat="acme-fix")
        before = self.record("acme-fix")
        blocked.mkdir()
        self.addCleanup(blocked.rmdir)
        term.keys("r")
        term.wait("Is a directory")
        self.assertEqual(self.record("acme-fix"), before)

    def test_a_40_cell_screen_puts_each_rows_numbers_under_its_name(self):
        shown = self.models(40)[1]
        at = shown.index("  builds · best 100.0")
        self.assertEqual(shown[at + 1:at + 10], [
            "    quality  a task", "    Acme Max 5 max", "      100.0  $20.00  ≈ tie · no harness",
            "    Acme Mid 5 high", "       98.0  $15.00  ≈ tie",
            "    Acme Max 5 high", "       95.5  $10.00  ★ pick · no harness",
            "      r takes Acme Mid 5 high, 98.0,", "      $15.00"])
        self.assertIn("  as good    within ‹ 5 › points of the", shown)


if __name__ == "__main__":
    unittest.main()
