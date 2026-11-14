"""A board's release is named as a seat's model is: without its maker's family word where more
than numbers follow it, a hyphen a space, between two numbers a point, so `Claude Fable 5.2` is
`Fable 5.2`, `GPT-6.1 Sol` is `6.1 Sol`, `GPT-5.5` is `GPT 5.5` and `Acme Top 1`, no family word
of a shipped manifest, stays.  The owner, 10 Nov 2026: "I always want it just to be the model
name, number and effort."  `ak models --json`, its role lines and its bars say the same names.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked (tests/test_key_role_choices.py),
its harness a fake over the shipped manifest listing the four releases, each configured; judged
by `ak models --json` and `ak models` on 100 cells.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV
from test_key_models_bars import bars
from test_key_models_role_lines import said
from test_key_role_choices import hold

# Release, its name as the board says it and as ak does, quality in every role and cost a task,
# each at `high`, cheapest first: four choices, three points apart
ROWS = [("acme-top-1", "Acme Top 1", "Acme Top 1", 91, 1),
        ("gpt-5-5", "GPT-5.5", "GPT 5.5", 94, 2),
        ("gpt-6-1-sol", "GPT-6.1 Sol", "6.1 Sol", 97, 3),
        ("claude-fable-5-2", "Claude Fable 5.2", "Fable 5.2", 100, 4)]
SAID = [name for _, _, name, *_ in ROWS]
BOARD = [name for _, name, *_ in ROWS if name not in SAID]
CONFIGURED = {"top": "acme-top-1", "gpt": "gpt-5-5", "sol": "gpt-6-1-sol",
              "fable": "claude-fable-5-2"}
# [defaults]: each role runs another of them, and what its line names
USES = {"orchestrator": "Fable 5.2 high", "executor": "6.1 Sol high", "reviewer": "GPT 5.5 high"}


class NameNoFamilyWord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
            f"{release}\t{name}\thigh\n" for release, name, *_ in ROWS))
        akconfig.write(home, {name: {"harness": "claude", "model": release}
                              for name, release in CONFIGURED.items()},
                       orchestrator="fable", workers=["sol"], reviewers=["gpt"])
        hold(home, [(release, name, "high", quality / 100 - 0.1, cost)
                    for release, name, _, quality, cost in ROWS])

    def test_json_names_each_release_without_its_family_word(self):
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        found = json.loads(done.out)
        for role in ("orchestrate", "execute", "review"):
            with self.subTest(role=role):
                self.assertEqual([row["name"] for row in found[role]["choices"]], SAID)
                self.assertEqual(found[role]["others"], [])

    def test_the_role_lines_and_bars_say_the_same_names(self):
        done = self.home.ak("models", env={**ENV, "COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.out + done.err)
        lines = said(done.out)
        for word, model in USES.items():
            with self.subTest(role=word):
                self.assertTrue(any(line.startswith(f"{word} {model} ") for line in lines),
                                done.out)
                self.assertEqual([bar["name"] for bar in bars(done.out, word)], SAID, done.out)
        self.assertEqual([name for name in BOARD if any(name in line for line in lines)], [],
                         done.out)


if __name__ == "__main__":
    unittest.main()
