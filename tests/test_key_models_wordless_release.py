"""A release Artificial Analysis names with no letter or digit takes no other board's numbers:
an Arena row named so too, `???` beside a release named `!!!`, leaves the models screen's answer
as it was.  One named with spaces or hyphens alone is labelled by its slug, as one it names
nothing is.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked
(tests/test_key_role_choices.py) with one release's name then made whitespace or punctuation,
its harness a fake running both releases, each configured; judged by `ak models --json` with and
without an Arena row of no letter or digit.  Fails against /bin/false.
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
    return json.loads(done.out)


class WordlessRelease(unittest.TestCase):
    def test_a_release_named_with_no_letter_or_digit_takes_no_other_board_s_row(self):
        for name, model in (("  \n", "???"), ("!!!", "~~~")):
            with self.subTest(name=name):
                alone = answer(name, None)
                self.assertTrue(alone["execute"]["choices"], alone)
                self.assertEqual(answer(name, model), alone)

    def test_a_release_named_with_spaces_or_hyphens_alone_is_labelled_by_its_slug(self):
        for name in ("  \n", "---"):
            with self.subTest(name=name):
                found = answer(name, None)
                self.assertEqual({row["name"] for role in ("orchestrate", "execute", "review")
                                  for row in found[role]["choices"]
                                  if row["release"] == "acme-bevel-1"}, {"Acme Bevel 1"}, found)


if __name__ == "__main__":
    unittest.main()
