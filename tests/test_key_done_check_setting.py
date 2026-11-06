"""`c`'s `Done check` row opens a page of its own, as `Weekly audit`'s does: `On`, on until the
owner turns it off, and `Model`, the seat's reviewer until the owner picks a model, each change
written to `[done_check]` in config.toml at once.

Space on `On` writes `on = false`, and again `on = true`.  Enter on `Model` opens the seat's
reviewer and every model offered, ● on the one in use: taking the second model writes it as
`model`, and `ak orch check` then takes its turn on that model; taking the seat's reviewer takes
`model` out.  Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py), NO_COLOR,
then `ak orch check` on a seat of tests/fixtures/akseat.py whose transcript the test writes,
the harnesses fakes of tests/fixtures/fakeadapter.py, one for each model.  Fails against
`/bin/false`.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
MARK, OPEN = "  ↑↓←→ move   ␣ mark   esc back", "  ↑↓←→ move   ⏎ open   esc back"
PICK = "  ↑↓←→ move   ␣ mark   ⏎ pick   esc back"
CONVERSATION = "5b8d2f61-3c4a-4e9b-a7d0-1f6e8c2b9a35"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def shows(*patterns, keys=None):
    """A screen with a line matching each of `patterns`, and its key line `keys` where given."""
    return lambda screen: all(any(re.fullmatch(pattern, line) for line in lines(screen))
                              for pattern in patterns) and keys in (None, key_line(screen))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class DoneCheckSetting(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))

    def setting(self):
        return akconfig.read(self.home).get("done_check", {})

    def check(self):
        """`ak orch check acme` on a seat whose reviewer is fable, its owner having asked one
        thing; the harnesses whose fake took a turn."""
        seat = Seat(self.home, "acme", model="fable", alive=False,
                    record={"conversation": CONVERSATION})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        self.home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", json.dumps(
            {"type": "user", "timestamp": "2026-11-06T10:00:00Z",
             "message": {"role": "user", "content": "Add a retry button."}}) + "\n")
        before = {harness: fake.n for harness, fake in self.fakes.items()}
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 0, done.out + done.err)
        return {harness for harness, fake in self.fakes.items() if fake.n > before[harness]}

    def test_on_turns_off_and_on_and_the_model_picked_makes_the_check(self):
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        self.term.keys(*["Down"] * 6)       # past both models, Models, Subscriptions, Discord
        self.term.wait(shows(r"› Done check +on · the seat's reviewer"))   # and Weekly audit
        self.term.keys("Enter")
        self.term.wait(shows(r"agentkit · config · done check +\d\d:\d\d", r"› On +● on",
                             r"  Model +the seat's reviewer", keys=MARK))
        self.term.keys("Space")
        self.term.wait(shows(r"› On +○ off", keys=MARK))
        self.assertEqual(self.setting(), {"on": False})
        self.term.keys("Space")
        self.term.wait(shows(r"› On +● on", keys=MARK))
        self.assertEqual(self.setting(), {"on": True})

        self.term.keys("Down", "Enter")
        self.term.wait(shows(r"›   ● the seat's reviewer", r"    ○ Fable 5.1",
                             r"    ○ GPT-6-Astra", keys=PICK))
        self.term.keys("Down", "Down", "Enter")
        self.term.wait(shows(r"› Model +GPT-6-Astra", keys=OPEN))
        self.assertEqual(self.setting(), {"on": True, "model": "astra"})
        self.assertEqual(self.check(), {"codex"})

        self.term.keys("Enter")
        self.term.wait(shows(r"    ○ the seat's reviewer", r"›   ● GPT-6-Astra", keys=PICK))
        self.term.keys("Up", "Up", "Enter")
        self.term.wait(shows(r"› Model +the seat's reviewer", keys=OPEN))
        self.assertEqual(self.setting(), {"on": True})
        self.assertEqual(self.check(), {"claude"})


if __name__ == "__main__":
    unittest.main()
