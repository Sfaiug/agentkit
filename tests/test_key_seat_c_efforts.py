"""On a seat's `c`, an effort step and `r` change that seat's own efforts, in its record, and
nothing else: no other seat's record and not config.toml, whose entries are what new seats take.

The owner (24 Oct 2026): inside a session, `c` edits only that session.  Black-box: the program
`AK_BIN` names, as the popup over one of two seats on one model at the same efforts
(tests/fixtures/akseat.py), in a person's terminal (tests/fixtures/akterm.py), its harnesses
the fakes of tests/fixtures/fakeadapter.py, judged by what the terminal shows, the seats'
records and config.toml; this test fails against `/bin/false`.
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

SEATS = ("acme-fix", "acme-ask")
EFFORTS = {"opus": {"effort": "xhigh"}, "astra": {"effort": "xhigh"}}
KEYS = "  ↑↓←→ move   ⏎ choose   r recommended   esc back"
# A board asked is a proxy nobody answers: what boards.json holds is all `r` reads.
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
# The boards as asked just now, every measure ak scores carried: Opus 5.5 at max the only one
# scored to orchestrate and execute, GPT-6-Astra at max the only one to review.
OPUS = {"aa.briefcaseBreakdown.overall.elo": 1500, "aa.terminalBench40": 0.5,
        "aa.intelligenceIndex": 70, "aa.intelligenceIndexCostPerTask.cost.total": 1.0,
        "arena.agent_task_outcome_explicit": 0.5, "arena.agent_steerability": 0.5,
        "arena.agent_bash_reliability": 0.5, "arena.webdev": 1500,
        "livebench.long_agentic": 50, "livebench.coding": 50, "livebench.cost_coding": 1.0}
ASTRA = {"aa.deepsecBench": 0.5, "aa.omniscience": 50, "aa.intelligenceIndex": 70,
         "arena.text_factuality.coding": 1500, "arena.text_style_control.coding": 1500,
         "livebench.reasoning": 50}
PREFIX = {"artificialanalysis.ai": "aa.", "arena.ai": "arena.", "livebench.ai": "livebench."}
IDENTITY = {"slug": "", "release": "", "maker": "", "deprecated": False}


def boards():
    now = time.time()
    return {board: {"asked_at": now, "fetched_at": now, "error": None, "build": "", "rows": [
        {"model": model, "effort": "max", **(IDENTITY if prefix == "aa." else {}),
         "values": {column: value for column, value in values.items()
                    if column.startswith(prefix)}}
        for model, values in (("claude-opus-5-5", OPUS), ("gpt-6-astra", ASTRA))]}
        for board, prefix in PREFIX.items()}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def opus_effort(screen):
    """The effort Opus 5.5's row shows, the last word on it."""
    return next(line.split()[-1] for line in lines(screen) if line.lstrip("› ").startswith("Opus 5.5"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatEfforts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        cls.seats = {name: Seat(home, name, model="opus",
                                record={"reviewers": ["astra"], "efforts": EFFORTS})
                     for name in SEATS}
        cls.config = home.path / ".agentkit" / "config.toml"

    def setUp(self):
        # each case starts from the config and the records as the seats were opened with them
        akconfig.write(self.home, ["opus", "astra"], workers=["opus"])
        for name, seat in self.seats.items():
            self.home.write(f".agentkit/state/session-{name}.json", seat.record)
        self.given = self.config.read_bytes()

    def c(self, seat):
        """`c` in the popup over `seat`, Opus 5.5's row highlighted."""
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": seat, **OFFLINE})
        # ends this case's menu, keeping the terminal's server for the next case
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        screen = term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)
        self.assertIn(f"  For  {seat}", lines(screen))
        return term, screen

    def record(self, name):
        return json.loads((self.home.path / f".agentkit/state/session-{name}.json").read_text())

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def others_kept(self):
        self.assertEqual(self.config.read_bytes(), self.given)
        self.assertEqual(self.record("acme-ask")["efforts"], EFFORTS)

    def test_a_step_on_a_seat_s_c_is_that_seat_s_alone(self):
        term, screen = self.c("acme-fix")
        self.assertEqual(opus_effort(screen), "xhigh")
        term.keys("Right", "Right", "Right", "Enter")      # onto the effort, and a step
        term.wait(lambda screen: opus_effort(screen) == "max")
        self.until(lambda: self.record("acme-fix")["efforts"]["opus"] == {"effort": "max"},
                   "acme-fix's record never took the step")
        self.assertEqual(self.record("acme-fix")["efforts"]["astra"], EFFORTS["astra"])
        self.others_kept()
        self.assertEqual(opus_effort(self.c("acme-ask")[1]), "xhigh")

    def test_r_on_a_seat_s_c_takes_the_recommended_efforts_into_its_record_alone(self):
        self.home.write(".agentkit/state/boards.json", boards())
        term, _ = self.c("acme-fix")
        term.keys("r")
        term.wait(lambda screen: "r take recommended" in key_line(screen))
        term.keys("r")
        self.until(lambda: self.record("acme-fix")["efforts"] == {
            "opus": {"effort": "xhigh", "exec_effort": "max"},
            "astra": {"effort": "xhigh", "review_effort": "max"}},
            "acme-fix's record never took the recommended efforts")
        self.others_kept()


if __name__ == "__main__":
    unittest.main()
