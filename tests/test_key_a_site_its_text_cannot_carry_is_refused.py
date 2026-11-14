"""`ak hand-in` refuses a finding or follow-up at a file whose path its site's text cannot carry.

ak writes a handed-in site as the text `path:line - what - why` and reads the site back from that
text to tell whether an open fix already stands there, so it takes no site whose path holds a line
break, a colon before a digit, or whitespace at either end: two files would read as one site.  It
refuses such a site with exit 2, saying what a site's path cannot hold, and records nothing; a
path holding `*`, a space inside or ` - ` is taken as before.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, as tests/test_key_hand_in_finding_rows.py
drives it.
"""

from itertools import count
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

LINE = "return s.split(',')"
WHAT, WHY = "empty input gives ['']", "callers expect []"
REFUSED = "ak hand-in: name a file whose path holds no line break, no colon before a digit and " \
          "no whitespace at either end: ak reads the site back from its path:line text\n"
CANNOT = {"a line break": "two\nlines.py", "a colon before a digit": "widget:1-a.py",
          "a leading space": " lead.py", "a trailing space": "trail.py "}
CAN = ("beta app/api.py", "alpha*/api.py", "notes - draft.md")


class ASiteItsTextCannotCarry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.ws = cls.home.path / "ws"
        for name in (*CANNOT.values(), *CAN):
            cls.home.write(f"ws/{name}", LINE + "\n")
        cls.turns = count(1)

    def hand_in(self, *argv):
        """A fresh reviewer turn's record file, as the loop opens one, and one hand-in to it."""
        turn = self.home.write(f"turns/{next(self.turns)}.jsonl", json.dumps(
            {"kind": "turn", "workspace": str(self.ws), "role": "reviewer",
             "findings": []}) + "\n")
        before = turn.read_text()
        done = self.home.ak("hand-in", *argv, env={"AK_HAND_IN": str(turn)}, cwd=self.ws)
        return done, before, turn.read_text()

    def test_a_site_its_text_cannot_carry_is_refused_and_nothing_is_recorded(self):
        for case, name in CANNOT.items():
            for argv in (["finding", f"{name}:1", WHAT, WHY, "--quote", LINE],
                         ["follow-up", f"{name}:1", WHAT, WHY, "--run", "false"]):
                with self.subTest(case, kind=argv[0]):
                    done, before, after = self.hand_in(*argv)
                    self.assertEqual((done.code, done.out, done.err), (2, "", REFUSED))
                    self.assertEqual(after, before)

    def test_a_path_holding_a_star_a_space_inside_or_a_dash_is_taken(self):
        for name in CAN:
            with self.subTest(name):
                done, before, after = self.hand_in("finding", f"{name}:1", WHAT, WHY,
                                                   "--quote", LINE)
                self.assertEqual((done.code, done.out, done.err), (0, "", ""))
                row = json.loads(after[len(before):])
                self.assertEqual(row, {"kind": "finding", "path": name, "line": 1, "what": WHAT,
                                       "why": WHY, "evidence": {"quote": LINE}})


if __name__ == "__main__":
    unittest.main()
