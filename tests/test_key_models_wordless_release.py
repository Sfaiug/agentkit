"""A release Artificial Analysis names with no letter or digit, or with no text, takes no
other board's numbers: an Arena row named `???` beside `!!!`, or `7` beside the number `7`,
leaves the models screen's answer as it was.  One whose name is not text, or is spaces or
hyphens alone, is labelled by its slug, as one it names nothing is.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked
(tests/test_key_role_choices.py) with one release's name then made whitespace, punctuation or
a number, its harness a fake running both releases, each configured; judged by `ak models
--json` with and without such an Arena row.  Fails against /bin/false.
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


def answer(name, model):
    """`ak models --json` with Acme Bevel 1's release named `name`, and an Arena row named
    `model` holding the worst agent share where `model` is not None."""
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
                row["release"]["name"] = name
        if model is not None:
            boards["arena.ai"]["rows"].append(
                {"model": model, "effort": "high", "values": {"arena.agent": 0}})
        held.write_text(json.dumps(boards))
        done = home.ak("models", "--json", env=ENV)
    assert done.code == 0, done.out + done.err
    found = json.loads(done.out)
    # the tasks by team span the moment each call asked
    # (tests/test_key_models_json_counts_tasks_by_team.py)
    found.pop("runs", None)
    return found


def labels(found):
    return {row["name"] for role in ("orchestrate", "execute", "review")
            for row in found[role]["choices"] if row["release"] == "acme-bevel-1"}


class WordlessRelease(unittest.TestCase):
    def test_a_release_whose_name_names_nothing_takes_no_other_board_s_row(self):
        for name, model in (("  \n", "???"), ("!!!", "~~~"), (7, "7")):
            with self.subTest(name=name):
                alone = answer(name, None)
                self.assertTrue(alone["execute"]["choices"], alone)
                self.assertEqual([row["release"] for row in alone["review"]["choices"]],
                                 ["acme-awl-1", "acme-bevel-1"], alone)
                self.assertEqual(answer(name, model), alone)

    def test_a_release_whose_name_is_not_text_is_labelled_by_its_slug(self):
        self.assertEqual(labels(answer(7, None)), {"Acme Bevel 1"})

    def test_a_release_named_with_spaces_or_hyphens_alone_is_labelled_by_its_slug(self):
        for name in ("  \n", "---"):
            with self.subTest(name=name):
                self.assertEqual(labels(answer(name, None)), {"Acme Bevel 1"})


if __name__ == "__main__":
    unittest.main()
