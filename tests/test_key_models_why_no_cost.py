"""A release compared whose rows have a quality on the boards and no price is among a role's
`others`, after those with a cost, its best row with the why `no cost`, by null, and a null
`cost`: the owner turns models on at `p` to compare them (5 Nov 2026), so none goes unsaid.  Its
why page lists it under `not shown`, its quality and that no board prices it; it is never a bar
and never a step of ← or →, as it has no cost to stand at: one used stands as the best choice.
A row a board prices that your runs and plans give no cost, as only releases no board prices
ran, is `not converted` instead.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked with invented releases of
one maker (tests/test_key_role_choices.py), its harness a fake listing each of them, each
configured; judged by `ak models --json`, the screen of 100 cells (tests/fixtures/akterm.py)
and config.toml; and the boards, logins' weeks and finished runs of
tests/test_key_picks_priced_in_usage.py.  Fails against /bin/false.
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
from test_key_models_answer import ENV, lines
from test_key_models_bars import bars
import test_key_picks_priced_in_usage as priced
from test_key_role_choices import hold

# Release, name, quality in every role and cost a task, each at `high`, cheapest first; Bare's
# quality between Mid's and Top's, so a step through it would stand there were it priced
ROWS = [("acme-base-1", "Acme Base 1", 90, 2),
        ("acme-mid-1", "Acme Mid 1", 93, 4),
        ("acme-dear-1", "Acme Dear 1", 92, 6),     # Mid is as good for less
        ("acme-top-1", "Acme Top 1", 97, 10),
        ("acme-bare-1", "Acme Bare 1", 95, None)]  # no board prices it
CONFIGURED = {release.split("-")[1]: {"harness": "claude", "model": release}
              for release, *_ in ROWS}
CHOICES = ["Acme Base 1", "Acme Mid 1", "Acme Top 1"]
# (name, why, by, its cost null)
OTHERS = [("Acme Dear 1", "beaten", "Acme Mid 1", False), ("Acme Bare 1", "no cost", None, True)]
# The orchestrator's bars, left to right: each name and its why, None on a choice
BARS = [("Acme Base 1", None), ("Acme Mid 1", None), ("Acme Dear 1", "░ beaten"),
        ("Acme Top 1", None)]
HEADING = "orchestrator · three choices · one more shaded"


def drawn(screen):
    """The orchestrator's bars on `screen` as BARS has them, None before they are drawn."""
    try:
        return [(bar["name"], bar["why"]) for bar in bars(screen, "orchestrator")]
    except (StopIteration, ValueError, IndexError):
        return None


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WhyNoCost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
            f"{release}\t{name}\thigh\n" for release, name, *_ in ROWS))
        hold(home, [(release, name, "high", quality / 100 - 0.1, cost)
                    for release, name, quality, cost in ROWS])

    def answered(self, orchestrator="top"):
        """`ak models --json` over CONFIGURED, orchestrating on `orchestrator`."""
        akconfig.write(self.home, CONFIGURED, orchestrator=orchestrator)
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)

    def orchestrating(self, release):
        """config.toml once [defaults] orchestrate on a model of it running `release`."""
        deadline = time.monotonic() + 30
        while True:
            cfg = akconfig.read(self.home)
            if cfg["models"][cfg["defaults"]["orchestrator"]]["model"] == release:
                return cfg
            self.assertLess(time.monotonic(), deadline, f"nothing took {release}")
            time.sleep(0.05)

    def screen(self, orchestrator):
        """`r recommended` on `c`, orchestrating on `orchestrator`, once its orchestrator's bars
        are drawn."""
        akconfig.write(self.home, CONFIGURED, orchestrator=orchestrator)
        term = Terminal(self.home, size=(100, 50), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait(lambda screen: "\n  " + HEADING + "\n" in screen and drawn(screen) == BARS)
        return term

    def test_json_lists_it_in_each_roles_others_after_those_with_a_cost(self):
        found = self.answered()
        for role in ("orchestrate", "execute", "review"):
            with self.subTest(role=role):
                self.assertEqual([row["name"] for row in found[role]["choices"]], CHOICES)
                self.assertEqual([(row["name"], row["why"], row["by"] and row["by"]["name"],
                                   row["cost"] is None) for row in found[role]["others"]],
                                 OTHERS)

    def test_its_why_page_lists_it_not_shown_saying_no_board_prices_it(self):
        bare = self.answered()["orchestrate"]["others"][-1]
        term = self.screen("bare")
        term.keys("Enter")
        page = lines(term.wait(lambda screen: "\n  why " in screen and lines(
            screen.rstrip())[-1] == "  esc back").rstrip())
        self.assertIn("  why Acme Bare 1 high orchestrates", page)
        self.assertIn("  cost       no cost", page)
        self.assertIn(f"  not shown  Acme Bare 1 high, {bare['quality']:.1f}: no board prices it",
                      page)

    def test_the_bars_draw_none_for_it_and_the_arrows_pass_it(self):
        term = self.screen("bare")       # the bars stand as BARS: none is Bare's
        # used, it stands as the best choice: ← takes the one under that, → nothing
        for key, release in (("Left", "acme-mid-1"), ("Right", "acme-top-1"),
                             ("Left", "acme-mid-1"), ("Left", "acme-base-1"),
                             ("Right", "acme-mid-1"), ("Right", "acme-top-1"),
                             ("Right", "acme-top-1"), ("Left", "acme-mid-1")):
            term.keys(key)
            self.orchestrating(release)
            term.wait(lambda screen: drawn(screen) == BARS)


class NotConverted(unittest.TestCase):
    # its home: Anvil, Bloom and Dune ran builds and reviews, no orchestration
    setUp, cache, answer = (getattr(priced.PicksPricedInUsage, name)
                            for name in ("setUp", "cache", "answer"))

    def test_with_only_releases_no_board_prices_run_one_a_board_prices_is_not_converted(self):
        path = self.home.path / ".agentkit/state/boards.json"
        held = json.loads(path.read_text())
        for row in held["artificialanalysis.ai"]["rows"]:
            if row["model"] in ("Anvil", "Bloom", "Dune") and row["effort"] == "high":
                row["values"] = {key: value for key, value in row["values"].items()
                                 if not key.endswith(".costPerTask")}
        path.write_text(json.dumps(held))
        self.assertEqual([(row["name"], row["why"], row["board_cost"]) for row in
                          self.answer()["orchestrate"]["others"]],
                         [("Crown", "not converted", 100), ("Bloom", "no cost", None),
                          ("Anvil", "no cost", None), ("Echo", "not converted", 20),
                          ("Dune", "no cost", None)])


if __name__ == "__main__":
    unittest.main()
