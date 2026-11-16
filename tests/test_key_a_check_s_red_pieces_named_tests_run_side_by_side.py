"""The tests a check's red pieces named run again alone side by side, taking no turn, while the
host's cores, less the threads that want one now, leave room for a piece; one after another where
they leave none, or the host shows no such count.

Black-box: `AK_BIN` checks a landing line through tests/fixtures/akline.py on a host whose readings
(AK_HOST_READINGS) give the threads that want a core as `cpu_wanted`, or none.  Two pieces of its
suite fail their first go, each naming its one test; run alone, that test marks its start in the
project's Git storage and passes once the other's has started there too, or once the test here
releases it; its piece then passes whole.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

CORES = 3
MEETS = """storage=$(git rev-parse --git-common-dir)
mkdir "$storage/failed-{me}" 2>/dev/null && exit 1
[ -n "${{AK_ONLY:-}}" ] || exit 0
touch "$storage/alone-{me}"
until [ -e "$storage/alone-{other}" ] || [ -e "$storage/release" ]; do sleep 0.1; done
"""
# Seconds the second go has to start once the first has, where they go one after another: a slow
# start only hides a go beside it, so load can pass a fault here but never fail a fix.
MORE = 10


class ACheckSRedPiecesNamedTestsRunSideBySide(unittest.TestCase):
    def alone_together(self, wanted, seconds):
        """How many of the two named tests run alone at once while `wanted` threads want a core
        (None: the host shows no such count), the second given `seconds` to start once the first
        has; released then, both pass and the member lands."""
        line = Line({"t/a.sh": MEETS.format(me="a.sh", other="b.sh"),
                     "t/b.sh": MEETS.format(me="b.sh", other="a.sh")})
        self.addCleanup(line.close)
        home, storage = line.home, line.rig.path / ".git"
        home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        line.member({"fix-1.txt": "x\n"})
        readings = {"cpus": CORES, "load": 0, "free_mb": 900, "mem_total_mb": 900}
        if wanted is not None:
            readings["cpu_wanted"] = wanted
        lander = home.spawn("run", "--lander", line.line,
                            env={"AK_HOST_READINGS": json.dumps(readings)})

        def alone():
            return len(list(storage.glob("alone-*")))

        for goes, wait in ((1, 300), (2, seconds)):
            deadline = time.monotonic() + wait
            while alone() < goes and time.monotonic() < deadline:
                self.assertIsNone(lander.poll(), home.log("spawn-1.err").read_text())
                time.sleep(0.2)
        together = alone()
        (storage / "release").touch()
        self.assertEqual(lander.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        self.assertIn("land", line.verdict(1))
        self.assertEqual(line.runs().count(("alone", "")), 2, line.runs())
        return together

    def test_named_tests_run_side_by_side_while_the_cores_have_room_for_a_piece(self):
        self.assertEqual(self.alone_together(CORES - 1, 300), 2)

    def test_named_tests_run_one_after_another_while_the_threads_waiting_fill_the_cores(self):
        self.assertEqual(self.alone_together(CORES, MORE), 1)

    def test_named_tests_run_one_after_another_where_the_host_shows_no_threads_waiting(self):
        self.assertEqual(self.alone_together(None, MORE), 1)


if __name__ == "__main__":
    unittest.main()
