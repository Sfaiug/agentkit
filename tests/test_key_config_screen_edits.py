"""A seat's `c` steps its effort, moves it once asked, and adds a model to config.toml.

`c` is where the owner changes the models without opening a file: Enter on a model's effort
steps the seat's own one up, into its record at once, config.toml as it was; Enter on another
model's orchestrator mark asks under the
matrix first, as the owner said on 24 Oct ("when pressing a different orch, it should ask me
to confirm. As this restarts the session."): Esc keeps the record and the pane as they were,
and `Move` moves the seat, its record naming the new orchestrator and its tmux session running
that model's harness, config.toml as it was; and `+ add a
model` walks harness, model and effort, each picked from a list, the models being the ones the
harness's adapter lists, and writes the new model to config.toml under its provider.
Black-box: the program `AK_BIN` names, as the popup over a seat as ak leaves it
(tests/fixtures/akseat.py) in a person's terminal (tests/fixtures/akterm.py), its harnesses the
fakes of tests/fixtures/fakeadapter.py, judged by what the terminal shows, config.toml, the
seat's record and its pane; this test fails against `/bin/false`.  The terminal has no colour
(NO_COLOR), so the mark the keys are on is bracketed, `[○]`, where a colour terminal reverses it.
"""

import json
import sys
from pathlib import Path
import time
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from fixtures import akconfig, fakeadapter

SEAT = "atoll-ask"
# `x_custom` is a key ak does not know; config.toml is the owner's, so a save must keep it.
MODELS = {"fable": {"harness": "claude", "effort": "xhigh", "x_custom": 1},
          "astra": {"harness": "codex", "effort": "high"}}
CATALOG = "m1\tModel One\tlow medium high"     # what the claude adapter's `models` lists
# A step reads the adapter's list if it answers at once, else the manifest's: both name fable's
# efforts the same, as a real Claude's does, so the bar reads the same either way.
FABLE_LISTED = "claude-fable-5-1\tFable 5.1\tlow medium high xhigh max"
KEYS = "  ↑↓←→ move   ⏎ choose   r recommended   esc back"   # wherever the highlight is
PAGE_KEYS = "  ↑↓←→ move   ⏎ choose   esc back"   # a page under it, with no `r`

def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(rows(screen)) if line), "")


def body(screen):
    """What the frame holds between its rule and its key line, blank lines at either end left
    out."""
    lines = rows(screen)
    while lines and not lines[-1]:
        lines.pop()
    block = lines[2:-1]
    while block and not block[-1]:
        block.pop()
    while block and not block[0]:
        block.pop(0)
    return block


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ConfigScreenEdits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.fakes = fakeadapter.install(cls.home, claude="pass", codex="pass")
        cls.seat = Seat(cls.home, SEAT, model="fable", record={"workers": ["astra"]})
        cls.record = cls.home.path / ".agentkit" / "state" / f"session-{SEAT}.json"

    def setUp(self):
        # Each case starts from the same config, in a menu of its own: one reads its harnesses'
        # model lists once and keeps them.
        self.config = akconfig.write(self.home, MODELS, workers=["fable", "astra"])
        self.given = tomllib.loads(self.config.read_text())
        self.term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT})
        # ends this case's menu, keeping the terminal's server for the next case
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: f"› 1  {SEAT}" in screen and "esc leave" in screen)
        self.term.keys("c")
        self.term.wait(lambda screen: key_line(screen) == KEYS and "› Fable 5.1" in screen)

    def test_enter_on_an_effort_steps_the_seat_s_up_into_its_record_not_config_toml(self):
        self.fakes["claude"].answer("models", FABLE_LISTED)
        self.term.keys("Right", "Right", "Right")
        self.term.wait(lambda screen: "› Fable 5.1     ●      □        □     ▰▰▰▰▱   xhigh"
                       in rows(screen))
        self.term.keys("Enter")
        self.term.wait(lambda screen: "› Fable 5.1     ●      □        □     ▰▰▰▰▰   max"
                       in rows(screen))
        self.assertEqual(json.loads(self.record.read_text())["efforts"], {"fable": {"effort": "max"}})
        self.assertEqual(tomllib.loads(self.config.read_text()), self.given)

    def pane(self):
        return self.home.tmux("display-message", "-p", "-t", f"={SEAT}:",
                              "#{pane_id} #{pane_pid}").out.strip()

    def asked(self, model):
        """Enter on the highlighted orchestrator mark, and the question it asks under the rows."""
        self.term.keys("Enter")
        return self.term.wait(lambda screen: f"  Restart {SEAT} on {model}?" in rows(screen)
                              and "  It starts a new conversation, handed the one it had."
                              in rows(screen) and "› ✓ Keep" in rows(screen)
                              and "  ✗ Move" in rows(screen))

    def test_another_model_s_orchestrator_mark_asks_and_moves_the_seat_on_move(self):
        # the command it opens astra with leaves the pane it runs in, writing nothing on it: a
        # Codex pane's text would be its composer's
        ran = self.fakes["codex"].dir / "astra-pane"
        ran.unlink(missing_ok=True)
        self.fakes["codex"].answer("interactive", f"sh -c 'echo $TMUX_PANE >{ran}; exec sleep 600'")
        # as Codex's adapter does: its TUI takes no conversation id of ak's making
        self.fakes["codex"].answer("interactive", "", 3, given=["new"])
        self.term.keys("j")
        self.term.wait(lambda screen: "› GPT-6-Astra  [○]     ■        ■     ▰▰▰▱▱▱  high"
                       in rows(screen))
        pane, record = self.pane(), self.record.read_text()
        opened = len(self.fakes["codex"].calls("interactive"))
        # asked, nothing moved yet; Esc keeps the record, the pane and config.toml as they were
        self.asked("GPT-6-Astra")
        self.assertEqual((self.pane(), self.record.read_text()), (pane, record))
        self.term.keys("Escape")
        screen = self.term.wait(lambda screen: key_line(screen) == KEYS)
        self.assertIn("› GPT-6-Astra  [○]     ■        ■     ▰▰▰▱▱▱  high", rows(screen))
        self.assertEqual((self.pane(), self.record.read_text()), (pane, record))
        self.assertEqual(len(self.fakes["codex"].calls("interactive")), opened)
        self.assertFalse(ran.exists())
        self.assertEqual(tomllib.loads(self.config.read_text()), self.given)
        # asked again, and `Move` moves it
        self.asked("GPT-6-Astra")
        self.term.keys("Down", "Enter")
        screen = self.term.wait(lambda screen: "› GPT-6-Astra  [●]     ■        ■     ▰▰▰▱▱▱  high"
                                in rows(screen))
        self.assertIn("  Fable 5.1     ○      □        □     ▰▰▰▰▱   xhigh", rows(screen))
        self.assertEqual(key_line(screen), KEYS)
        now = json.loads(self.record.read_text())
        self.assertEqual((now["orchestrator"], now["workers"]), ("astra", ["astra"]))
        # the seat's pane runs what Codex's adapter says opens astra, in place of Fable's harness
        deadline = time.monotonic() + 30
        while not (ran.exists() and ran.read_text().endswith("\n")):    # written whole
            self.assertLess(time.monotonic(), deadline, "the seat never ran astra's harness")
            time.sleep(0.2)
        pane = self.home.tmux("display-message", "-p", "-t", f"={SEAT}:", "#{pane_id}").out
        self.assertEqual(ran.read_text().strip(), pane.strip())
        self.assertEqual(self.fakes["codex"].calls("interactive")[-1]["argv"][:2],
                         ["gpt-6-astra", "high"])
        self.assertEqual(tomllib.loads(self.config.read_text()), self.given)
        # back on Fable, as the other cases find the seat
        self.term.keys("k")
        self.asked("Fable 5.1")
        self.term.keys("Down", "Enter")
        self.term.wait(lambda screen: "› Fable 5.1    [●]     □        □     ▰▰▰▰▱   xhigh"
                       in rows(screen))
        self.assertEqual(json.loads(self.record.read_text())["orchestrator"], "fable")

    def test_add_a_model_walks_harness_model_and_effort_and_writes_the_model(self):
        self.fakes["claude"].answer("models", CATALOG)
        self.term.keys("j", "j")
        screen = self.term.wait(lambda screen: "› + add a model" in rows(screen))
        self.assertEqual(key_line(screen), KEYS)
        self.term.keys("Enter")
        # each list draws once its choices are in hand; a harness's models are asked of it
        screen = self.term.wait(lambda screen: "›   claude  Claude" in rows(screen))
        self.assertTrue(rows(screen)[0].startswith("agentkit · config · add a model"), screen)
        self.assertEqual(body(screen), ["  harness", "›   claude  Claude", "    codex   ChatGPT"])
        self.assertEqual(key_line(screen), PAGE_KEYS)
        self.term.keys("Enter")
        screen = self.term.wait(lambda screen: "›   Model One  m1" in rows(screen))
        self.assertEqual(body(screen), ["  harness  claude · Claude", "  model",
                                        "›   Model One  m1"])
        self.assertEqual(key_line(screen), PAGE_KEYS)
        self.term.keys("Enter")
        screen = self.term.wait(lambda screen: "›   low" in rows(screen))
        self.assertEqual(body(screen), ["  harness  claude · Claude", "  model    Model One · m1",
                                        "  effort", "›   low", "    medium", "    high"])
        self.assertEqual(key_line(screen), PAGE_KEYS)
        self.term.keys("Enter")
        # the row's cells, under whichever name the screen gives a model it has just added
        cells = "[○]     □        □     ▰▱▱     low"
        # read once the frame is drawn down to its key line
        screen = self.term.wait(lambda screen: key_line(screen) == KEYS and any(
            line.startswith("› ") and line.endswith(cells) for line in rows(screen)))
        lines = rows(screen)
        row = next(line for line in lines if line.startswith("› ") and line.endswith(cells))
        # the new model sits with its harness's others, after them
        self.assertEqual(lines.index("Codex") - lines.index("Claude Code"), 3)
        self.assertEqual(lines.index(row), lines.index("Codex") - 1)
        models = tomllib.loads(self.config.read_text())["models"]
        self.assertEqual(models["model-one"], {"harness": "claude", "model": "m1",
                                               "effort": "low", "provider": "anthropic"})
        self.assertEqual({name: models[name] for name in MODELS}, self.given["models"])
        self.assertTrue(self.fakes["claude"].calls("models"))


if __name__ == "__main__":
    unittest.main()
