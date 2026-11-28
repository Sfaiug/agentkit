"""Where no row has the Intelligence Index, as when Artificial Analysis stops publishing it, each
role is still rated on its own benchmarks, each one's best of every row; where a row has it,
each one's best is of the rows that have it, a row without it rating above 100.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked
(tests/test_key_role_choices.py) with the index then kept on one release's row or on none, its
harness a fake running both releases, each configured; judged by `ak models --json`.  Fails
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
from test_key_role_choices import ROLES, hold

# Release, its name on the board, quality in every role and cost a task, at `high`
ROWS = [("acme-awl-1", "Acme Awl 1", 99, 1), ("acme-bevel-1", "Acme Bevel 1", 100, 2)]


def choices(indexed):
    """Each role's choices, (release, quality), on the boards holding `ROWS` with the index on
    the row of the release `indexed` names alone, or on none."""
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
            if row["release"]["slug"] != indexed:
                row["values"].pop("aa.intelligenceIndex", None)
        held.write_text(json.dumps(boards))
        done = home.ak("models", "--json", env=ENV)
    assert done.code == 0, done.out + done.err
    found = json.loads(done.out)
    return {role: [(row["release"], round(row["quality"], 6)) for row in found[role]["choices"]]
            for role in ROLES}


class ModelsRatedWithoutTheIndex(unittest.TestCase):
    def test_with_no_row_indexed_every_role_rates_each_row_against_the_best_of_all(self):
        self.assertEqual(choices(None), dict.fromkeys(
            ROLES, [("acme-awl-1", 99), ("acme-bevel-1", 100)]))

    def test_with_one_row_indexed_the_best_is_of_that_row(self):
        self.assertEqual(choices("acme-awl-1"), dict.fromkeys(
            ROLES, [("acme-awl-1", 100), ("acme-bevel-1", 101)]))


if __name__ == "__main__":
    unittest.main()
