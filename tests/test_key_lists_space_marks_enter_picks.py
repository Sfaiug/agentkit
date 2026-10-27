"""On the pages `c` opens Space marks and Enter opens or picks, as on `c` itself.

The owner (27 Oct 2026): "everywhere enter is for like opening, new page and stuff like that,
and space should be select / unselect".  On `Models` Space takes a model in or out and its
list stays open, Enter closing it; on `Weekly audit` Space flips `On`, Enter opens
`Orchestrator`'s list, where Space moves the ● and Enter takes the highlighted model and closes
it, each key line naming only what Space and Enter do there; on `Subscriptions` Enter or a
click runs the lit act and Space runs nothing.  Black-box: `AK_BIN`'s menu in a terminal
(tests/fixtures/akterm.py), its harnesses faked (tests/fixtures/fakeadapter.py), judged by
what the terminal shows, config.toml and the logins run; NO_COLOR.  This test fails against
`/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ choose   n new   c config   esc leave"
MARK, OPEN = "  ↑↓←→ move   ␣ mark   esc back", "  ↑↓←→ move   ⏎ open   esc back"
PICK = "  ↑↓←→ move   ␣ mark   ⏎ pick   esc back"
CLOSE = "  ↑↓←→ move   ␣ mark   ⏎ close   esc back"
FABLE_LISTED = "claude-fable-5-1\tFable 5.1\tlow medium high xhigh max"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ListsSpaceMarksEnterPicks(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        self.fakes["claude"].answer("models", FABLE_LISTED)
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))
        self.term.keys("c")
        self.term.wait("› Fable 5.1")

    def to(self, row, keys=None):
        """The highlight moved, a line at a time, onto the line that starts `row`; the screen,
        once its key line is `keys` where given."""
        for _ in range(20):
            shown = lines(self.term.wait(lambda screen: any(
                line.startswith(f"{mark} {row}") for line in lines(screen) for mark in "› ")
                and any(line.startswith("› ") for line in lines(screen))))
            now = next(n for n, line in enumerate(shown) if line.startswith("› "))
            if shown[now].startswith(f"› {row}"):
                return self.term.wait(lambda screen: lines(screen)[now].startswith(f"› {row}")
                                      and keys in (None, key_line(screen)))
            there = next(n for n, line in enumerate(shown) if line.startswith(f"  {row}"))
            self.term.keys("Down" if there > now else "Up")
            self.term.wait(lambda screen: lines(screen)[now] != shown[now])
        self.fail(f"the highlight never reached {row}")

    def audit(self):
        return akconfig.read(self.home)["audit"]

    def test_on_models_space_takes_a_model_in_and_out_and_enter_closes_the_list(self):
        self.to("Models", "  ↑↓←→ move   ⏎ open   r recommended   a apply to all sessions"
                          "   esc back")
        self.term.keys("Enter")
        self.to("Claude Code", OPEN)
        self.term.keys("Enter")
        self.to("  ■ Fable 5.1", CLOSE)
        self.term.keys("Space")
        self.to("  □ Fable 5.1", CLOSE)                # the list open still
        self.assertNotIn("fable", akconfig.read(self.home)["models"])
        shown = lines(self.term.screen())             # a click on a mark does as Space does
        row = next(n for n, line in enumerate(shown) if "□ Fable 5.1" in line) + 1
        self.term.type(f"\x1b[<0;20;{row}M\x1b[<0;20;{row}m")
        self.to("  ■ Fable 5.1", CLOSE)
        before = akconfig.read(self.home)
        self.assertIn("fable", before["models"])
        self.term.keys("Enter")
        self.term.wait(lambda screen: "› Claude Code" in screen and "Fable 5.1" in screen
                       and "■" not in screen and key_line(screen) == OPEN)
        self.assertEqual(akconfig.read(self.home), before)

    def test_on_weekly_audit_space_flips_on_and_enter_opens_orchestrator_s_list_to_pick(self):
        self.to("Weekly audit")
        self.term.keys("Enter")
        self.to("On", MARK)
        self.term.keys("Enter")                       # nothing: On is a mark
        self.term.keys("Space")
        self.term.wait("› On            ● on")
        self.assertIs(self.audit()["on"], True)
        self.term.keys("Enter", "Down")               # nothing, then onto Orchestrator
        self.to("Orchestrator", OPEN)
        self.assertIs(self.audit()["on"], True)
        self.term.keys("Enter")
        self.to("  ● Fable 5.1", PICK)
        self.term.keys("Down", "Space")
        self.to("  ● GPT-6-Astra", PICK)              # the ● moved, the list open still
        self.assertEqual(self.audit()["orchestrator"], "astra")
        self.term.keys("Up", "Enter")
        self.to("Orchestrator  Fable 5.1", OPEN)      # taken, and the list closed
        self.assertNotIn("○", self.term.screen())
        self.assertEqual(self.audit()["orchestrator"], "fable")

    def test_on_subscriptions_enter_or_a_click_runs_an_act_and_space_runs_nothing(self):
        acts = "  ↑↓←→ move   ⏎ log in again   esc back"
        self.to("Subscriptions")
        self.term.keys("Enter")
        self.to("Claude", acts)
        self.term.keys("Space", "Down")               # Space first: had it run, Down waits
        self.to("ChatGPT")
        self.assertEqual(self.fakes["claude"].calls("login"), [])
        self.term.keys("Up")
        self.to("Claude", acts)
        self.term.keys("Enter")
        self.term.wait(lambda screen: len(self.fakes["claude"].calls("login")) == 1)
        shown = lines(self.to("Claude", acts))
        row = next(n for n, line in enumerate(shown) if "[↻ log in again]" in line)
        column = shown[row].index("[↻ log in again]") + 3
        self.term.type(f"\x1b[<0;{column};{row + 1}M\x1b[<0;{column};{row + 1}m")
        self.term.wait(lambda screen: len(self.fakes["claude"].calls("login")) == 2)


if __name__ == "__main__":
    unittest.main()
