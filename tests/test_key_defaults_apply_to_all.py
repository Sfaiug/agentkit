"""`a` on a fresh window's `c` gives new seats' models and efforts to every open seat, once asked.

The owner (24 Oct 2026) wants the defaults `c` sets for new seats applied to every live session
on request.  `a` asks on a card how many open seats it changes and which restart, each one on
another orchestrator than [defaults]'s: Esc leaves every record as it was; `Apply` gives each
seat [defaults]'s executors and reviewers and the entries' efforts for those models in its
record, and moves the one on another orchestrator to [defaults]'s, config.toml as it was.
Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) over
two seats as ak leaves them (tests/fixtures/akseat.py), its harnesses the fakes of
tests/fixtures/fakeadapter.py, judged by what the terminal shows, the seats' records and
config.toml; this test fails against `/bin/false`.
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

KEYS = "  ↑↓←→ move   ⏎ choose   r recommended   a apply to all sessions   esc back"
MODELS = {"fable": {"harness": "claude", "effort": "xhigh"}, "opus": "claude",
          "astra": {"harness": "codex", "effort": "high", "review_effort": "medium"}}
SEATS = {"acme-same": {"model": "fable", "screen": "claude-prompt-pane.txt",
                       "record": {"workers": ["opus"], "reviewers": ["fable"],
                                  "efforts": {"fable": {"effort": "max"},
                                              "opus": {"effort": "low"}}}},
         "acme-other": {"model": "astra", "screen": "codex-prompt-pane.txt",
                        "record": {"workers": ["astra"], "reviewers": ["astra"],
                                   "efforts": {"astra": {"effort": "low"}}}}}
ROLES = ("orchestrator", "workers", "reviewers", "efforts")


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class DefaultsApplyToAll(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        self.config = akconfig.write(self.home, MODELS, workers=["fable"], reviewers=["astra"])
        self.given = self.config.read_text()
        for name, seat in SEATS.items():
            Seat(self.home, name, **seat)
        self.term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("c config")
        self.term.keys("c")
        self.term.wait(lambda screen: key_line(screen) == KEYS)

    def records(self):
        """Each seat's models and efforts as its record holds them; the menu stamps the rest."""
        return {name: {key: record.get(key) for key in ROLES} for name, record in (
            (name, json.loads((self.home.path / f".agentkit/state/session-{name}.json")
                              .read_text())) for name in SEATS)}

    def asked(self):
        self.term.keys("a")
        return self.term.wait(lambda screen: {
            "  Give new seats' models and efforts to 2 open sessions?",
            "  acme-other restarts on Fable 5.1.", "› ✓ Keep", "  ✗ Apply"} <= set(lines(screen)))

    def test_esc_on_the_card_leaves_every_seat_as_it_was(self):
        before = self.records()
        self.asked()
        self.assertEqual(self.records(), before)
        self.term.keys("Escape")
        self.term.wait(lambda screen: key_line(screen) == KEYS
                       and "  ✗ Apply" not in lines(screen))
        self.assertEqual(self.records(), before)
        self.assertEqual(self.config.read_text(), self.given)

    def test_apply_gives_every_seat_the_defaults_and_moves_the_other_one(self):
        self.asked()
        self.term.keys("Down", "Enter")
        deadline = time.monotonic() + 30
        while self.records()["acme-other"]["orchestrator"] != "fable":
            self.assertLess(time.monotonic(), deadline, "acme-other never moved to fable")
            time.sleep(0.2)
        self.term.wait(lambda screen: key_line(screen) == KEYS)
        for name, record in self.records().items():
            with self.subTest(seat=name):
                self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                                 ("fable", ["fable"], ["astra"]))
                self.assertEqual(record["efforts"]["fable"], {"effort": "xhigh"})
                self.assertEqual(record["efforts"]["astra"],
                                 {"effort": "high", "review_effort": "medium"})
        self.assertEqual(self.config.read_text(), self.given)

    def test_a_seat_s_own_c_has_no_a_though_its_record_is_gone(self):
        Seat(self.home, "acme-bare", model="fable")
        (self.home.path / ".agentkit/state/session-acme-bare.json").unlink()
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme-bare"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("c config")
        term.keys("c")
        term.wait(lambda screen: "  For  new seats" in lines(screen) and key_line(screen)
                  == "  ↑↓←→ move   ⏎ choose   r recommended   esc back")


if __name__ == "__main__":
    unittest.main()
