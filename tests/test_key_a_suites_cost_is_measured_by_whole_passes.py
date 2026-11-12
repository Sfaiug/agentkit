"""A suite's cost is measured by every whole pass: a check whose pieces waited for places another
check held records what its pieces needed while they ran, and its line's next check takes fewer.

Black-box: `AK_BIN` checks two landing lines in one Home through tests/fixtures/akline.py, on a
host whose readings (AK_HOST_READINGS) fit four pieces at the initial cost and give each box a
day of waiting for a core.  Each test marks its start in its project's Git storage and runs
until the test here releases it.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

HELD = """cd "$(git rev-parse --git-common-dir)" && touch "started-${0##*/}"
until [ -e release ]; do sleep 0.1; done
"""
FIT = 4         # the places the host's readings fit at the initial cost
OTHERS = 2      # of them the other line's check holds
# Seconds more for pieces past those counted to start: a slow start only hides a place, so load
# can pass a fault here but never fail a fix.
MORE = 10
READINGS = {"AK_HOST_READINGS": json.dumps(
    {"cpus": 3, "load": 0, "free_mb": 16000, "cpu_wait_seconds": 86400})}


class ASuitesCostIsMeasuredByWholePasses(unittest.TestCase):
    def test_a_pass_whose_pieces_waited_for_places_leaves_the_next_one_a_place(self):
        acme = Line({f"t/{name}.sh": HELD for name in "abcdef"})
        self.addCleanup(acme.close)
        home = acme.home
        home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        other = Line({f"t/{name}.sh": HELD for name in "ab"}, home=home, name="widget")

        def started(line):
            return len(list((line.rig.path / ".git").glob("started-*")))

        def check(line, files):
            """Its lander, checking a new member that adds `files`."""
            line.member(files)
            return home.spawn("run", "--lander", line.line, env=READINGS)

        def wait(line, lander, pieces, seconds):
            deadline = time.monotonic() + seconds
            while started(line) < pieces and lander.poll() is None and (
                    time.monotonic() < deadline):
                time.sleep(0.2)

        def ends(line, lander, spawn):
            """Release `line`'s tests; its lander, `home.spawn`'s `spawn`th, lands its last."""
            storage = line.rig.path / ".git"
            (storage / "release").touch()
            self.assertEqual(lander.wait(timeout=300), 0,
                             home.log(f"spawn-{spawn}.err").read_text())
            self.assertIn("land", line.verdict(len(line.members)))
            for mark in (*storage.glob("started-*"), storage / "release"):
                mark.unlink()

        holder = check(other, {"fix.txt": "x\n"})
        wait(other, holder, OTHERS, 300)
        self.assertEqual(started(other), OTHERS)
        waiter = check(acme, {"fix-1.txt": "x\n"})
        wait(acme, waiter, FIT - OTHERS, 300)
        wait(acme, waiter, FIT, MORE)
        self.assertEqual(started(acme), FIT - OTHERS)    # the rest of its pieces wait for a place
        ends(acme, waiter, 2)
        ends(other, holder, 1)

        lander = check(acme, {"fix-2.txt": "x\n"})
        wait(acme, lander, 1, 300)
        wait(acme, lander, FIT, MORE)
        self.assertEqual(started(acme), 1)
        ends(acme, lander, 3)


if __name__ == "__main__":
    unittest.main()
