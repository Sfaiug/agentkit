"""A model added on `Models` reads on every screen as its listing named it there.

The owner (10 Nov 2026): "Every single time we add a new model, it should be added and named
correctly."  A model is named off its id wherever no listing is at hand, and for a maker that
spells its name its own way that is another name: OpenCode lists `longcat-2.5-free` as `LongCat
2.5 Free`, which its id reads as `Longcat 2.5 Free`.  So the entry added keeps the listing's name
as `label` where its id says another, and every screen reads that `label` by the same rule.

Black-box: `AK_BIN` in a person's terminal (tests/fixtures/akterm.py) adds models on `c`'s
`Models` off its harnesses' fakes' listings (tests/fixtures/fakeadapter.py), then from a pipe,
where every seat's row opens, names them on a seat's row; judged by the screens and
config.toml.  Fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

CLAUDE = ("claude-fable-5-1\tFable 5.1\tlow medium high xhigh max\n"
          "acme/longcat-2.5-free\tLongCat 2.5 Free\tlow medium high\n")
CODEX = "gpt-6-astra\tGPT-6-Astra\tlow medium high xhigh\ngpt-7.2-vega\tGPT-7.2-Vega\tlow high\n"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AModelKeepsItsListedName(unittest.TestCase):
    def home(self, models):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", CLAUDE)
        fakes["codex"].answer("models", CODEX)
        akconfig.write(home, models)
        return home

    def seat_row(self, home, **record):
        """The line under seat fix-api's name on ak's screen read from a pipe: its models."""
        Seat(home, "fix-api", record=record)
        done = home.ak(input="\n", env={"COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        shown = lines(done.out) + [""]
        at = next((n for n, line in enumerate(shown) if re.match(r"[› ] 1  fix-api ", line)),
                  None)
        self.assertIsNotNone(at, done.out)
        return shown[at + 1]

    def to(self, term, row):
        """The highlight moved down, a line at a time, onto the line that starts `› {row}`."""
        for _ in range(20):
            shown = lines(term.screen())
            if any(line.startswith(f"› {row}") for line in shown):
                return
            lit = next(line for line in shown if line.startswith("› "))
            term.keys("Down")
            term.wait(lambda screen: lit not in lines(screen))
        self.fail(f"the highlight never reached {row}")

    def tick(self, term, harness, label):
        """`label` taken in under `harness`'s row of `Models`, and that row closed again."""
        self.to(term, harness)
        term.keys("Enter")
        term.wait(f"□ {label}")
        self.to(term, f"  □ {label}")
        term.keys("Space")
        term.wait(lambda screen: f"›   ■ {label}" in lines(screen))
        term.keys("Escape")
        term.wait(lambda screen: "■" not in screen)

    def test_a_model_added_on_models_reads_as_listed_and_one_whose_id_says_it_keeps_no_label(self):
        home = self.home({"fable": {"harness": "claude", "effort": "high"},
                          "astra": {"harness": "codex", "effort": "high"}})
        term = Terminal(home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("› Fable 5.1")
        self.to(term, "Models")
        term.keys("Enter")
        term.wait("› Claude Code")
        self.tick(term, "Claude Code", "LongCat 2.5 Free")
        self.tick(term, "Codex", "7.2 Vega")
        models = akconfig.read(home)["models"]
        self.assertEqual(models["longcat-free"], {
            "harness": "claude", "model": "acme/longcat-2.5-free", "effort": "high",
            "provider": "anthropic", "label": "LongCat 2.5 Free"})
        self.assertEqual(models["vega"], {"harness": "codex", "model": "gpt-7.2-vega",
                                          "effort": "high", "provider": "openai"})
        row = self.seat_row(home, orchestrator="longcat-free", workers=["vega"],
                            reviewers=["longcat-free"])
        self.assertIn("LongCat 2.5 Free high orchestrates", row)
        self.assertIn("7.2 Vega high builds", row)

    def test_an_entry_written_with_a_label_reads_so_and_one_without_reads_off_its_id(self):
        home = self.home({"minimax": {"harness": "claude", "model": "acme/minimax-m3.1-flash-free",
                                      "label": "MiniMax M3.1 Flash Free"},
                          "nemotron": {"harness": "claude",
                                       "model": "acme/nemotron-3.5-super-vl-free"}})
        row = self.seat_row(home, orchestrator="minimax", workers=["nemotron"],
                            reviewers=["minimax"])
        self.assertIn("MiniMax M3.1 Flash Free high orchestrates", row)
        self.assertIn("Nemotron 3.5 Super Vl Free high builds", row)


if __name__ == "__main__":
    unittest.main()
