"""The log names each command that runs here as what it is: only one that names `AK_SHARD` a
suite, any other a check, and a piece of a suite pinned alone that piece, by its share.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, with no suite helper set up.  The one member has a `# once` check of
its own and adds a test that fails, which the target's tip does not hold: asked for that test
alone the tip proves nothing, so the lander asks it for the piece whole too.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

NOT_SENT = "runs here: command is not sent to the suite helper"


class TheLogNamesWhatRunsHere(unittest.TestCase):
    def test_a_check_is_a_check_and_a_pinned_piece_its_share(self):
        line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        line.member({"t/bad.sh": "false\n"})
        (line.members[0] / "task.md").write_text(
            "# fix-1\n\n## Done when\n```bash\ntrue  # once\n```\n")
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        said = [row.partition("] ")[2] for row in done.out.splitlines()]    # less its time
        # the member's own check and the suite, once each: nothing else is called either
        named = sorted(row for row in said if row.startswith(("check runs", "suite runs")))
        self.assertEqual(named, [f"check {NOT_SENT} (does not name AK_SHARD)",
                                 "suite runs here: no suite helper set up"], said)
        piece = line.verdict(1)["fix"]["piece"]
        for pinned in (f"{piece}, its failed tests alone", piece):
            self.assertIn(f"AK_SHARD={pinned} {NOT_SENT} (pinned piece)", said)


if __name__ == "__main__":
    unittest.main()
