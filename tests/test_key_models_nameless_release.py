"""A release Artificial Analysis gives no name is named by its slug, as ak says a model's, and
the models screen still offers every release in each role, named or not, as a choice or another.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked
(tests/test_key_role_choices.py) with one release's name then cleared, its harness a fake
running both releases, each configured; judged by `ak models --json`.  Fails against /bin/false.
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

# Release, its name on the board, quality in every role and cost a task, at `high`
ROWS = [("acme-awl-1", "Acme Awl 1", 99, 1), ("acme-bevel-1", "Acme Bevel 1", 100, 2)]


class NamelessRelease(unittest.TestCase):
    def test_a_nameless_release_is_named_by_its_slug_beside_a_named_one(self):
        with Home() as home:
            fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
                f"{release}\t{release}\thigh\n" for release, *_ in ROWS))
            akconfig.write(home, {release: {"harness": "claude", "model": release}
                                  for release, *_ in ROWS})
            hold(home, [(release, name, "high", quality / 100 - 0.1, cost)
                        for release, name, quality, cost in ROWS])
            held = home.path / ".agentkit/state/boards.json"
            boards = json.loads(held.read_text())
            for row in boards["artificialanalysis.ai"]["rows"]:
                if row["release"]["slug"] == "acme-bevel-1":
                    row["release"]["name"] = None
            held.write_text(json.dumps(boards))
            done = home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        found = json.loads(done.out)
        for role in ("orchestrate", "execute", "review"):
            with self.subTest(role=role):
                self.assertEqual({row["name"] for kind in ("choices", "others")
                                  for row in found[role][kind]}, {"Acme Awl 1", "Acme Bevel 1"})


if __name__ == "__main__":
    unittest.main()
