"""`r recommended` on `c` names its keys, ←→ change nothing, and ⏎ opens the why of the
orchestrator's first choice, its model at its effort being no row.  `r` takes each role's take at its effort: into new seats' [defaults] in a
window of its own, and into a seat's record alone, its orchestrator only said, over a seat; a
save that fails changes nothing and says why.

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
KEYS = "  ↑↓ role   ⏎ why   p models   r take   esc back"
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
            "workers": ["mid"], "reviewers": ["mid"]}) for name in SEATS}

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
                == ["mid", ["mid"], ["mid"]] and all(
                    efforts == {"effort": "low"} for efforts in record.get("efforts", {}).values()))

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_left_and_right_change_nothing(self):
        term, _ = self.models()
        term.keys("Left", "Right", "Enter")
        term.wait("why Crux 2 low orchestrates")
        self.assertEqual(self.config.read_bytes(), self.given)

    def test_the_key_line_names_each_key(self):
        _, shown = self.models()
        self.assertEqual(next(line for line in reversed(shown) if line), KEYS)

    def test_r_takes_each_roles_take_at_its_effort(self):
        term, _ = self.models()
        term.keys("r")
        self.until(lambda: akconfig.read(self.home)["defaults"].get("reviewers") == ["bolt"],
                   "r never took the answer")
        saved = akconfig.read(self.home)
        self.assertEqual(saved["defaults"], {"orchestrator": "bolt", "workers": ["bolt"],
                                             "reviewers": ["bolt"]})
        self.assertEqual(saved["models"]["bolt"]["effort"], "medium")
        self.assertEqual({key: saved["models"]["mid"].get(key) for key in (
            "effort", "exec_effort", "review_effort")},
            {"effort": "low", "exec_effort": None, "review_effort": None})
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
        self.until(lambda: self.record("acme-fix")["reviewers"] == ["bolt"], "r never took it")
        record = self.record("acme-fix")
        # its orchestrator is only said: moving the seat is its orchestrator mark's
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("mid", ["bolt"], ["bolt"]))
        self.assertEqual(record["efforts"]["bolt"],
                         {"effort": "low", "exec_effort": "medium", "review_effort": "medium"})
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


if __name__ == "__main__":
    unittest.main()
