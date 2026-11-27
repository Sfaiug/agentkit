"""The `Models` page offers `□` only the newest release of each line a harness lists, while a
model the config runs stays listed `■` whatever its release.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py), its
harnesses the fakes of tests/fixtures/fakeadapter.py, judged by what the terminal shows and
config.toml; this test fails against `/bin/false`.  The terminal has no colour (NO_COLOR).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal
from test_key_models_from_own_login import ticks
from test_key_models_page_defaults import MAIN_KEYS, MARK_KEYS, key_line, lines


def open_models(home, first_row):
    """Open `c` -> `Models` in `home`, starting with `first_row` highlighted on `c`."""
    term = Terminal(home, size=(100, 30), env={"NO_COLOR": "1"})
    term.wait(lambda screen: key_line(screen) == MAIN_KEYS)
    term.keys("c")
    term.wait(lambda screen: key_line(screen) == MARK_KEYS and f"› {first_row}" in screen)
    for _ in range(20):
        shown = lines(term.screen())
        if "› Models" in shown:
            break
        now = next(n for n, line in enumerate(shown) if line.startswith("› "))
        term.keys("Down")
        term.wait(lambda screen: lines(screen)[now] != shown[now])
    else:
        raise AssertionError("never reached Models")
    term.keys("Enter")
    term.wait(lambda screen: lines(screen)[0].startswith("agentkit · config · models"))
    return term


def harness_ticks(term, row, ready):
    """Open `row` on `Models`, return its `■`/`□` lines once `ready` appears, and close it."""
    for _ in range(20):
        shown = lines(term.screen())
        now = next(n for n, line in enumerate(shown) if line.startswith("› "))
        if shown[now].startswith(f"› {row}"):
            break
        there = next(n for n, line in enumerate(shown) if line.startswith(f"  {row}"))
        term.keys("Down" if there > now else "Up")
        term.wait(lambda screen: lines(screen)[now] != shown[now])
    else:
        raise AssertionError(f"never reached {row}")
    term.keys("Enter")
    listed = ticks(term.wait(lambda screen: ready in ticks(screen)))
    term.keys("Escape")
    term.wait(lambda screen: any(line.startswith(f"› {row}") for line in lines(screen))
              and "■" not in screen and "□" not in screen)
    return listed


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsPageNewestRelease(unittest.TestCase):
    def test_three_releases_of_one_line_and_another_line_offer_the_two_newest(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass")
        fakes["claude"].answer(
            "models",
            "claude-bolt-4-8\tBolt 4.8\thigh\n"
            "claude-bolt-5-5-fast\tBolt 5.5 Fast\thigh\n"
            "claude-bolt-5\tBolt 5\thigh\n"
            "claude-bolt-5-5\tBolt 5.5\thigh\n"
            "claude-plain\tPlain\thigh\n",
        )
        akconfig.write(home, {"plain": {"harness": "claude", "model": "claude-plain",
                                        "label": "Plain"}})
        term = open_models(home, "Plain")
        self.assertEqual(harness_ticks(term, "Claude Code", "■ Plain"),
                         ["□ Bolt 5.5 Fast", "□ Bolt 5.5", "■ Plain"])

    def test_release_numbers_compare_part_by_part_as_whole_numbers(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass")
        fakes["claude"].answer(
            "models",
            "claude-bolt-5-9\tBolt 5.9\thigh\n"
            "claude-bolt-5-10\tBolt 5.10\thigh\n"
            "claude-loom-5\tLoom 5\thigh\n"
            "claude-loom-5-1\tLoom 5.1\thigh\n"
            "claude-plain\tPlain\thigh\n",
        )
        akconfig.write(home, {"plain": {"harness": "claude", "model": "claude-plain",
                                        "label": "Plain"}})
        term = open_models(home, "Plain")
        self.assertEqual(harness_ticks(term, "Claude Code", "■ Plain"),
                         ["□ Bolt 5.10", "□ Loom 5.1", "■ Plain"])

    def test_an_older_release_the_config_runs_is_listed_beside_the_newest(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer(
            "models",
            "claude-bolt-4-8\tBolt 4.8\thigh\n"
            "claude-bolt-5\tBolt 5\thigh\n"
            "claude-bolt-5-5\tBolt 5.5\thigh\n",
        )
        akconfig.write(home, {"bolt": {"harness": "claude", "model": "claude-bolt-4-8",
                                       "label": "Bolt 4.8"},
                              "astra": "codex"},
                       workers=["bolt", "astra"])
        term = open_models(home, "Bolt 4.8")
        term.keys("Enter")
        listed = ticks(term.wait(lambda screen: "■ Bolt 4.8" in ticks(screen)))
        self.assertEqual(listed, ["■ Bolt 4.8", "□ Bolt 5.5"])
        # Space still takes the older configured release out
        term.keys("Space")
        term.wait(lambda screen: "□ Bolt 4.8" in ticks(screen))
        self.assertNotIn("bolt", akconfig.read(home)["models"])

    def test_two_harnesses_listing_one_line_each_offer_their_own_newest(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer(
            "models",
            "claude-bolt-5\tBolt 5\thigh\n"
            "claude-bolt-5-5\tBolt 5.5\thigh\n"
            "claude-plain\tPlain\thigh\n",
        )
        fakes["codex"].answer(
            "models",
            "codex-bolt-4-8\tBolt 4.8\thigh\n"
            "codex-bolt-5\tBolt 5\thigh\n"
            "codex-plain\tPlain\thigh\n",
        )
        akconfig.write(home, {"plain": {"harness": "claude", "model": "claude-plain",
                                        "label": "Plain"},
                              "other": {"harness": "codex", "model": "codex-plain",
                                        "label": "Plain"}},
                       workers=["plain", "other"])
        term = open_models(home, "Plain")
        self.assertEqual(harness_ticks(term, "Claude Code", "■ Plain"),
                         ["□ Bolt 5.5", "■ Plain"])
        self.assertEqual(harness_ticks(term, "Codex", "■ Plain"),
                         ["□ Bolt 5", "■ Plain"])


if __name__ == "__main__":
    unittest.main()
