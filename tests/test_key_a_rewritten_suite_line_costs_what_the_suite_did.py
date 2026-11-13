"""A rewritten `tests:` line starts at what the target's suite costs: a change's own line, which
no pass measured, takes no more places at its landing check than the target's line beside it.

Black-box: `AK_BIN` checks a landing line through tests/fixtures/akline.py on a host whose
readings (AK_HOST_READINGS) fit four pieces at the initial estimate and give each box a day of
waiting for a core, so the first change's check records its suite at a cost where one piece fits.
Each test marks its start in the project's Git storage, under the word its line gives it, and
runs until the test here takes that mark away.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import SUITE, Line, rules

HELD = """cd "$(git rev-parse --git-common-dir)" && start=$(mktemp "started-${1:-target}.XXXXXX")
while [ -e "$start" ]; do sleep 0.1; done
"""
READINGS = {"AK_HOST_READINGS": json.dumps(
    {"cpus": 3, "load": 0, "free_mb": 16000, "cpu_wait_seconds": 86400})}
# Seconds the rest of a line's pieces have to start once its first has: a slow start only hides
# a piece, so load can pass a fault here but never fail a fix.
MORE = 10


class ARewrittenSuiteLineCostsWhatTheSuiteDid(unittest.TestCase):
    def test_a_rewritten_line_starts_as_few_pieces_as_the_target_s(self):
        line = Line({f"t/{name}.sh": HELD for name in "abcdef"})
        self.addCleanup(line.close)
        line.home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        line.member({"fix-1.txt": "x\n"})
        self.check(line, 1)
        line.member({"AGENTS.md": rules(f"{SUITE} again")})
        self.assertEqual(self.check(line, 2), {"target": 1, "again": 1})

    def check(self, line, n):
        """Check member `n` and see it land, releasing each test once it started: for each line,
        by the word it gives its tests, the pieces started before its first was released."""
        storage = line.rig.path / ".git"
        lander = line.home.spawn("run", "--lander", line.line, env=READINGS)

        def starts():
            return [(start, start.stem.removeprefix("started-"))
                    for start in storage.glob("started-*")]

        together, deadline = {}, time.monotonic() + 600
        while lander.poll() is None and time.monotonic() < deadline:
            first = {word for _, word in starts()} - set(together)
            if first:
                time.sleep(MORE)
            held = starts()
            together.update({word: sum(seen == word for _, seen in held) for word in first})
            for start, word in held:
                if word in together:
                    start.unlink()
            time.sleep(0.2)
        self.assertEqual(lander.wait(timeout=60), 0,
                         line.home.log(f"spawn-{n}.err").read_text())
        self.assertIn("land", line.verdict(n))
        return together


if __name__ == "__main__":
    unittest.main()
