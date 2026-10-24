"""`c` in a window of its own offers `r recommended` as a seat's does; `r`, or a click on it,
opens the models screen, where `r` takes the recommendation into new seats' [defaults]: the
recommended rows' models orchestrate, build and review, each at its row's effort, saved at once,
no open seat changing.  A config that cannot be saved changes nothing and says why.

The owner opened `c` in a fresh window, found no `r`, and asked whether that is right (24 Oct
2026).  Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py)
beside a seat as ak leaves it (tests/fixtures/akseat.py), its harnesses the fakes of
tests/fixtures/fakeadapter.py, judged by what the terminal shows, the seat's record and
config.toml; this test fails against `/bin/false`.  The boards are held as just asked, and the
network is a proxy nobody answers on, so ak scores the rows below and asks no board.
"""

import json
import re
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
MAIN_KEYS = "  ↑↓ move   ⏎ open   n new   x stop   c config   esc leave"
MARK_KEYS = "  ↑↓←→ move   ⏎ mark   r recommended   esc back"
OFFLINE = {"https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9"}
# Each model perfect in one role on the boards, at an effort above the one the config runs it at:
# Opus orchestrates at xhigh, Fable builds at max, Astra reviews at xhigh.
BOARDS = {"arena.ai": [
              {"model": "claude-opus-5-5", "effort": "xhigh",
               "values": {"arena.agent_task_outcome_explicit": 1, "arena.agent_steerability": 1}},
              {"model": "claude-fable-5-1", "effort": "max",
               "values": {"arena.agent_bash_reliability": 1}}],
          "livebench.ai": [
              {"model": "claude-fable-5-1", "effort": "max", "values": {"livebench.coding": 100}},
              {"model": "gpt-6-astra", "effort": "xhigh", "values": {"livebench.reasoning": 100}}],
          "artificialanalysis.ai": [
              {"model": "claude-fable-5-1", "effort": "max", "values": {"aa.terminalBench40": 1}},
              {"model": "gpt-6-astra", "effort": "xhigh",
               "values": {"aa.deepsecBench": 1, "aa.omniscience": 100}}]}
LABELS = {"fable": "Fable 5.1", "opus": "Opus 5.5", "astra": "GPT-6-Astra"}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def marks(screen):
    """Each model's three marks on `c`, as `orch builds reviews`: `●■□`."""
    return {name: "".join(re.findall("[●○■□]", line.split(label, 1)[1]))
            for name, label in LABELS.items() for line in lines(screen)
            if line[2:].startswith(label) or line.startswith("› " + label)}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RInAFreshWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        cls.seat = Seat(home, "atoll-fix", model="fable",
                        record={"workers": ["opus"], "created": NOW - 900})

    def setUp(self):
        akconfig.write(self.home, {name: {"harness": "codex" if name == "astra" else "claude",
                                          "effort": "high"} for name in LABELS},
                       orchestrator="fable", workers=["opus"])
        self.home.write(".agentkit/state/session-atoll-fix.json", self.seat.record)
        self.home.write(".agentkit/state/boards.json", {
            board: {"asked_at": NOW, "fetched_at": NOW, "rows": rows, "error": None}
            for board, rows in BOARDS.items()})
        self.config = (self.home.path / ".agentkit/config.toml").read_bytes()

    def config_screen(self):
        """`c` in a window of its own, its marks new seats'."""
        term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1", **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait(lambda screen: key_line(screen) == MAIN_KEYS)
        term.keys("c")
        screen = term.wait(lambda screen: key_line(screen) == MARK_KEYS)
        self.assertIn("  For  new seats", lines(screen))
        self.assertEqual(marks(screen), {"fable": "●□□", "opus": "○■■", "astra": "○□□"})
        return term, screen

    def recommended(self, term):
        """The models screen, once the rows are scored and `r` takes them."""
        return term.wait(lambda screen: "agentkit · models · new seats" in screen
                         and "r take recommended" in key_line(screen))

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_r_takes_the_recommendation_into_new_seats_defaults(self):
        term, _ = self.config_screen()
        term.keys("r")
        self.recommended(term)
        term.keys("r")
        self.until(lambda: akconfig.read(self.home)["defaults"] == {
            "orchestrator": "opus", "workers": ["fable"], "reviewers": ["astra"]},
            "[defaults] never took the recommendation")
        models = akconfig.read(self.home)["models"]
        self.assertEqual((models["opus"]["effort"], models["fable"].get("exec_effort"),
                          models["astra"].get("review_effort")), ("xhigh", "max", "xhigh"))
        record = json.loads((self.home.path / ".agentkit/state/session-atoll-fix.json")
                            .read_text())
        self.assertEqual({key: record.get(key) for key in ("orchestrator", "workers", "reviewers")},
                         {"orchestrator": "fable", "workers": ["opus"], "reviewers": None})
        term.keys("Escape")
        screen = term.wait(lambda screen: key_line(screen) == MARK_KEYS)
        self.assertEqual(marks(screen), {"fable": "○■□", "opus": "●□□", "astra": "○□■"})

    def test_a_click_on_r_recommended_opens_the_models_screen(self):
        term, screen = self.config_screen()
        row = len(lines(screen.rstrip("\n")))
        col = key_line(screen).index("r recommended") + 1
        term.type(f"\x1b[<0;{col};{row}M")
        term.type(f"\x1b[<0;{col};{row}m")
        self.recommended(term)

    def test_a_config_that_cannot_be_saved_changes_nothing_and_says_why(self):
        # the save's temporary file cannot be written: a directory stands in its place
        blocked = self.home.path / ".agentkit/config.tmp"
        blocked.mkdir()
        self.addCleanup(blocked.rmdir)
        term, _ = self.config_screen()
        term.keys("r")
        self.recommended(term)
        term.keys("r")
        term.wait("Is a directory")
        self.assertEqual((self.home.path / ".agentkit/config.toml").read_bytes(), self.config)
        term.keys("Escape")
        screen = term.wait(lambda screen: key_line(screen) == MARK_KEYS)
        self.assertEqual(marks(screen), {"fable": "●□□", "opus": "○■■", "astra": "○□□"})


if __name__ == "__main__":
    unittest.main()
