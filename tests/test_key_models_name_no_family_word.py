"""A board's release is named as a seat's model is: without its maker's family word where more
than numbers follow it, a hyphen a space, between two numbers a point, so `Claude Fable 5.2` is
`Fable 5.2`, `GPT-6.1 Sol` is `6.1 Sol`, `GPT-5.5` is `GPT 5.5` and `Acme Top 1`, no family word
of a shipped manifest, stays.  The owner, 10 Nov 2026: "I always want it just to be the model
name, number and effort."  `ak models --json` says them so.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked
(tests/test_key_role_choices.py), its harness a fake over the shipped manifest listing the four
releases, each configured; judged by `ak models --json`.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV
from test_key_role_choices import hold

# Release, its name as the board says it and as ak does, quality in every role and cost a task,
# each at `high`, cheapest first: four choices, three points apart
ROWS = [("acme-top-1", "Acme Top 1", "Acme Top 1", 91, 1),
        ("gpt-5-5", "GPT-5.5", "GPT 5.5", 94, 2),
        ("gpt-6-1-sol", "GPT-6.1 Sol", "6.1 Sol", 97, 3),
        ("claude-fable-5-2", "Claude Fable 5.2", "Fable 5.2", 100, 4)]
SAID = [name for _, _, name, *_ in ROWS]
CONFIGURED = {"top": "acme-top-1", "five": "gpt-5-5", "solar": "gpt-6-1-sol",
              "story": "claude-fable-5-2"}


class NameNoFamilyWord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
            f"{release}\t{name}\thigh\n" for release, name, *_ in ROWS))
        akconfig.write(home, {name: {"harness": "claude", "model": release}
                              for name, release in CONFIGURED.items()},
                       orchestrator="story", workers=["solar"], reviewers=["five"])
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


if __name__ == "__main__":
    unittest.main()
