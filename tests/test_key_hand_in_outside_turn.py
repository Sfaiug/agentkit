"""`ak hand-in` works only inside a worker turn: anywhere else it is refused and writes nothing.

A worker hands in its findings and closes its turn with `ak hand-in`, which adds to the record
file the loop opened for that turn and named in `AK_HAND_IN`.  Typed in a seat's shell, an
owner's terminal or a turn whose record file is gone or broken, it must say so and exit 2, and
never start a record of its own or touch the file it was pointed at: a stray hand-in would close
or corrupt a turn nobody ran.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat

NO_TURN = "ak hand-in: hand-in needs an active worker turn; use it from the worker's shell\n"
INVALID = "ak hand-in: the worker turn's record file is invalid; ask the loop to retry\n"
# The reason on the line is the JSON reader's own, which each build words its own way.
UNREADABLE = re.compile(r"\Aak hand-in: cannot hand in this record: \S[^\n]*\n\Z")
RECORDS = (("done",), ("blocked", "the staging database is down"),
           ("not-needed", "fix-api already landed"))


def files(root):
    """Every file under `root` with what it holds."""
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


class OutsideATurn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.seat = Seat(cls.home, "acme", alive=False)

    def refused(self, env, said):
        """Every record handed in with `env` is refused, saying `said`; HOME is unchanged."""
        for record in RECORDS:
            with self.subTest(env=env, record=record):
                before = files(self.home.path)
                done = self.home.ak("hand-in", *record, env=env, cwd=self.seat.cwd)
                self.assertEqual((done.code, done.out), (2, ""), done.err)
                if isinstance(said, str):
                    self.assertEqual(done.err, said)
                else:
                    self.assertRegex(done.err, said)
                self.assertEqual(files(self.home.path), before)

    def test_with_no_turn_named_every_hand_in_is_refused(self):
        self.refused({}, NO_TURN)
        self.refused({"AK_HAND_IN": ""}, NO_TURN)

    def test_a_seats_own_shell_is_not_a_worker_turn(self):
        self.refused({"AGENTKIT_SESSION": self.seat.name}, NO_TURN)

    def test_a_turn_file_that_is_not_there_is_no_turn(self):
        gone = self.home.path / "turns" / "gone.jsonl"
        self.refused({"AK_HAND_IN": str(gone)}, NO_TURN)
        self.assertFalse(gone.exists())
        folder = self.home.path / "turns" / "folder"
        folder.mkdir(parents=True)
        self.refused({"AK_HAND_IN": str(folder)}, NO_TURN)

    def test_a_record_file_that_does_not_open_with_a_turn_is_invalid_and_kept(self):
        for name, text in (("empty", ""), ("other", '{"kind": "other"}\n'),
                           ("closed-first", '{"kind": "done"}\n')):
            path = self.home.write(f"turns/{name}.jsonl", text)
            self.refused({"AK_HAND_IN": str(path)}, INVALID)
            self.assertEqual(path.read_text(), text)

    def test_a_record_file_that_is_not_json_cannot_be_handed_in_and_is_kept(self):
        path = self.home.write("turns/garbage.jsonl", "garbage\n")
        self.refused({"AK_HAND_IN": str(path)}, UNREADABLE)
        self.assertEqual(path.read_text(), "garbage\n")


if __name__ == "__main__":
    unittest.main()
