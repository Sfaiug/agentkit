"""A check's second suite runs its pieces side by side, as its first did: a member that rewrites
the `tests:` line is checked by the target's line and then by its own, each on this host's turns.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py on a host that fits three pieces (AK_HOST_READINGS).  The member's line
gives every test the word `own`; a test given it marks its start in the project's Git storage,
where a boxed check may write, and runs until the test releases it.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, SUITE, rules

READINGS = {"AK_HOST_READINGS": json.dumps({"cpus": 4, "load": 0, "free_mb": 1300})}
HELD = """[ "${1:-}" = own ] || exit 0
storage=$(git rev-parse --git-common-dir)
echo start >>"$storage/marks"
until [ -e "$storage/release" ]; do sleep 0.1; done
"""


class ACheckSSecondSuiteTakesItsPlaces(unittest.TestCase):
    def test_a_rewritten_tests_line_s_pieces_run_side_by_side(self):
        line = Line({f"t/{name}.sh": HELD for name in "abcdef"})
        self.addCleanup(line.close)
        home, storage = line.home, line.rig.path / ".git"
        home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        line.member({"AGENTS.md": rules(f"{SUITE} own")})
        marks = storage / "marks"

        def started():
            return len(marks.read_text().splitlines()) if marks.exists() else 0

        lander = home.spawn("run", "--lander", line.line, env=READINGS)
        deadline = time.monotonic() + 300
        while started() < 3 and lander.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        together = started()
        (storage / "release").touch()
        self.assertEqual(lander.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        self.assertEqual(together, 3)
        self.assertIn("land", line.verdict(1))


if __name__ == "__main__":
    unittest.main()
