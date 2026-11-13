"""A run the lander blamed is woken for its fix as soon as no run its red waits on is in the
line, within the same pass: the line as it stands decides, not the line the pass started on.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py.  Of three members, their stacks checked side by side, the second turns
the suite red on top of the first, which lands, and is blamed; the check of the stack rebuilt
without it holds until the test lets it go.  Meanwhile the first merges, and the second's resume
is started, opening its `log.txt`.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import READINGS, Line, rules

TESTS = {"t/bad.sh": 'test ! -f bad.txt\n',
         "t/hold.sh": """storage=$(git rev-parse --git-common-dir)
[ -f member-3.txt ] && [ ! -f bad.txt ] || exit 0
touch "$storage/reached"
until [ -f "$storage/go" ]; do sleep 0.1; done
"""}


class ABlamedRunWakesOnceTheRunsAheadLeave(unittest.TestCase):
    def test_a_blamed_run_wakes_within_the_pass_once_the_run_ahead_merges(self):
        # a suite naming no share takes one turn of those pinned: the three stacks fit
        line = Line({**TESTS, "AGENTS.md": rules("sh suite.sh")})
        self.addCleanup(line.close)
        config = line.home.path / ".agentkit" / "config.toml"
        config.write_text("max_gates = 3\n" + config.read_text())
        for n in range(1, 4):
            line.member({f"member-{n}.txt": f"{n}\n", **({"bad.txt": "x\n"} if n == 2 else {})})
        storage, woken = line.rig.path / ".git", line.members[1] / "log.txt"
        lander = line.home.spawn("run", "--lander", line.line, env={"AK_HOST_READINGS": READINGS})
        said = line.home.log("spawn-1.err")

        def until(done, why):
            deadline = time.monotonic() + 300
            while not done():
                self.assertIsNone(lander.poll(), said.read_text())
                self.assertLess(time.monotonic(), deadline, why)
                time.sleep(0.2)

        until((storage / "reached").exists, "the stack rebuilt without the blamed run was never checked")
        self.assertEqual(line.verdict(2)["after"], {"fix-1": line.verdict(1)["land"]})
        self.assertFalse(woken.exists(), "woken while the run it waits on was in the line")
        ahead = line.members[0] / "run.json"
        ahead.write_text(json.dumps({**json.loads(ahead.read_text()), "state": "pass", "merged": True}))
        until(woken.exists, "the blamed run was not woken while the pass ran")
        (storage / "go").touch()
        self.assertEqual(lander.wait(timeout=300), 0, said.read_text())
        self.assertIn("fix", line.verdict(2))
        self.assertIn("land", line.verdict(3))


if __name__ == "__main__":
    unittest.main()
