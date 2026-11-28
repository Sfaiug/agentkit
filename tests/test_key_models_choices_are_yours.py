"""A role's choices are rows a take can take, spaced among those alone: one a configured model
runs, or one the harness a configured model runs on lists; a better row neither, as one no
harness lists or one listed only by a harness running no model of yours, moves none of them.
Of each other release its best row is among `others` with the why it would have were it taken:
`not set up`, by null, where it would be a choice; else `beaten`, `close` or `far below`.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked with invented releases of
one maker (tests/test_key_role_choices.py), its harness a fake listing four of them, three of
them configured, and a second fake listing one more; judged by `ak models --json`.  Fails
against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from fixtures.akboards import ENV
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
# On Claude, Base first and paying as it goes
CONFIGURED = {"base": {"harness": "claude", "model": "acme-base-1", "mode": "payg"},
              "mid": {"harness": "claude", "model": "acme-mid-1"},
              "top": {"harness": "claude", "model": "acme-top-1"}}
LISTED = (*(entry["model"] for entry in CONFIGURED.values()), "acme-gap-1")
CHOICES = ["Acme Base 1", "Acme Gap 1", "Acme Mid 1", "Acme Top 1"]
OTHERS = [("Acme Best 1", "not set up", None), ("Acme Side 1", "not set up", None),
          ("Acme Near 1", "close", "Acme Mid 1"), ("Acme Dear 1", "beaten", "Acme Mid 1"),
          ("Acme Low 1", "far below", None)]


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

    def test_json_chooses_rows_of_yours_and_says_why_of_each_other(self):
        akconfig.write(self.home, CONFIGURED, orchestrator="top")
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        found = json.loads(done.out)
        for role in ("orchestrate", "execute", "review"):
            with self.subTest(role=role):
                self.assertEqual([row["name"] for row in found[role]["choices"]], CHOICES)
                self.assertEqual([(row["name"], row["why"], row["by"] and row["by"]["name"])
                                  for row in found[role]["others"]], OTHERS)


if __name__ == "__main__":
    unittest.main()
