"""A role's choices are rows a take can take, spaced among those alone: one a configured model
runs, or one the harness a configured model runs on lists, whose model ← or → sets up beside
that one as it takes it, on its provider and with its `mode`, the owner's word of 5 Nov 2026; a
better row neither, as one no harness lists or one listed only by a harness running no model of
yours, moves none of them.  Of each other release its best row is among `others` with the why it
would have were it taken: `not set up`, by null, where it would be a choice, shaded so on
`r recommended` on `c`; else `beaten`, `close` or `far below`.  ← and → take each choice in turn,
from the best to the cheapest and back, and → on the best takes nothing: the one shaded past it
stays so (matrix.takes).  `ak models --json` and the screen say the same.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked with invented releases of
one maker (tests/test_key_role_choices.py), its harness a fake listing four of them, three of
them configured, and a second fake listing one more; judged by `ak models --json`, the screen of
100 cells (tests/fixtures/akterm.py) and config.toml.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV
from test_key_models_bars import bars
from test_key_role_choices import hold

# Release, name, quality in every role and cost a task, each at `high`, cheapest first
ROWS = [("acme-low-1", "Acme Low 1", 85, 1),       # 12 under Top: far below
        ("acme-base-1", "Acme Base 1", 89, 2),     # 11 under Best, a choice all the same
        ("acme-gap-1", "Acme Gap 1", 91, 3),       # listed, configured by none: a choice too
        ("acme-mid-1", "Acme Mid 1", 93, 4),
        ("acme-near-1", "Acme Near 1", 93.5, 5),   # half a point over Mid
        ("acme-side-1", "Acme Side 1", 95, 6),     # listed by Codex alone: would be a choice
        ("acme-top-1", "Acme Top 1", 97, 10),
        ("acme-dear-1", "Acme Dear 1", 92, 12),    # Mid is as good for less
        ("acme-best-1", "Acme Best 1", 100, 20)]   # better than every row of yours
# On Claude, Base first and paying as it goes, so a model set up beside it does too
CONFIGURED = {"base": {"harness": "claude", "model": "acme-base-1", "mode": "payg"},
              "mid": {"harness": "claude", "model": "acme-mid-1"},
              "top": {"harness": "claude", "model": "acme-top-1"}}
LISTED = (*(entry["model"] for entry in CONFIGURED.values()), "acme-gap-1")
CHOICES = ["Acme Base 1", "Acme Gap 1", "Acme Mid 1", "Acme Top 1"]
OTHERS = [("Acme Best 1", "not set up", None), ("Acme Side 1", "not set up", None),
          ("Acme Near 1", "close", "Acme Mid 1"), ("Acme Dear 1", "beaten", "Acme Mid 1"),
          ("Acme Low 1", "far below", None)]
# The orchestrator's bars, left to right: each name and its why, None on a choice; the best of
# the others fills the fifth place
BARS = [("Acme Base 1", None), ("Acme Gap 1", None), ("Acme Mid 1", None), ("Acme Top 1", None),
        ("Acme Best 1", "░ not set up")]
HEADING = "orchestrator · four choices · one more shaded"


def drawn(screen):
    """The orchestrator's bars on `screen` as BARS has them, None before they are drawn."""
    try:
        return [(bar["name"], bar["why"]) for bar in bars(screen, "orchestrator")]
    except (StopIteration, ValueError, IndexError):
        return None


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ChoicesAreYours(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        names = {release: name for release, name, *_ in ROWS}
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "".join(
            f"{release}\t{names[release]}\thigh\n" for release in LISTED))
        fakes["codex"].answer("models", "acme-side-1\tAcme Side 1\thigh\n")
        hold(home, [(release, name, "high", quality / 100 - 0.1, cost)
                    for release, name, quality, cost in ROWS])

    def configure(self, orchestrator):
        """CONFIGURED, orchestrating on `orchestrator`, as a test starts: a take before set up a
        model."""
        akconfig.write(self.home, CONFIGURED, orchestrator=orchestrator)

    def orchestrating(self, release):
        """config.toml once [defaults] orchestrate on a model of it running `release`."""
        deadline = time.monotonic() + 30
        while True:
            cfg = akconfig.read(self.home)
            if cfg["models"][cfg["defaults"]["orchestrator"]]["model"] == release:
                return cfg
            self.assertLess(time.monotonic(), deadline, f"nothing took {release}")
            time.sleep(0.05)

    def screen(self):
        """`r recommended` on `c`, once its orchestrator's bars are drawn."""
        term = Terminal(self.home, size=(100, 40), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait(lambda screen: "\n  " + HEADING + "\n" in screen and drawn(screen) == BARS)
        return term

    def test_json_chooses_rows_of_yours_and_says_why_of_each_other(self):
        self.configure("top")
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        found = json.loads(done.out)
        for role in ("orchestrate", "execute", "review"):
            with self.subTest(role=role):
                self.assertEqual([row["name"] for row in found[role]["choices"]], CHOICES)
                self.assertEqual([(row["name"], row["why"], row["by"] and row["by"]["name"])
                                  for row in found[role]["others"]], OTHERS)

    def test_the_screen_shades_one_not_set_up_and_the_arrows_take_each_choice(self):
        self.configure("top")
        term = self.screen()
        for key, release in (("Left", "acme-mid-1"), ("Left", "acme-gap-1"),
                             ("Left", "acme-base-1"), ("Right", "acme-gap-1"),
                             ("Right", "acme-mid-1"), ("Right", "acme-top-1"),
                             # → on Top takes nothing: the ← after it takes Mid, not Top off Best
                             ("Right", "acme-top-1"), ("Left", "acme-mid-1")):
            term.keys(key)
            self.orchestrating(release)

    def test_an_arrow_onto_a_choice_not_set_up_sets_its_model_up(self):
        self.configure("base")
        self.screen().keys("Right")
        cfg = self.orchestrating("acme-gap-1")
        made, beside = cfg["models"][cfg["defaults"]["orchestrator"]], cfg["models"]["base"]
        self.assertEqual([made[key] for key in ("harness", "provider", "mode")],
                         [beside[key] for key in ("harness", "provider", "mode")])
        self.assertEqual(len(cfg["models"]), len(CONFIGURED) + 1)


if __name__ == "__main__":
    unittest.main()
