"""The tagged cron line runs the kept version's keeper first, then the tick.

After a move, the version it replaced decides whether the move stays, and that runs outside the
new release, which may be what cannot start.  So while `~/.agentkit/tmp/keep/ak` is there and
executable, the line runs `back --when-broken` with it, under the line's own PATH and with its
output in the tick's log, and then the tick, whatever the keeper did.  Black-box: install.sh of
the checkout `AK_BIN` names installs a server on a Home of tests/fixtures/akbin.py made the
account's own by tests/fixtures/installer.py, and the tagged line's command runs as cron hands it
to sh.  A stand-in keeper prints its words, its PATH and when it ended, and the tick is seen by
the record it leaves in watch.json.  The tick asks the public boards and the shared browser on
loopback, so the whole file runs in one box with no host network (`rerun_boxed`).
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import BOXED, Home, rerun_boxed

# the kept version's ak: its words, its PATH and when it ended, on its output
KEEPER = """#!/bin/sh
printf '%s\\n' "$*" "$PATH"
{python} -c 'import time; print(time.time())'
exit {code}
"""


@unittest.skipUnless(BOXED, "no bwrap able to box the test here")
class TheCronLineRunsTheKeeperFirst(unittest.TestCase):
    def cron(self, keeper=None):
        """One run of the tagged line on a fresh server install, with a stand-in keeper exiting
        `keeper` unless that is None: the lines the run added to the tick's log, the PATH the
        line sets, and watch.json's record of the tick."""
        home = Home()
        self.addCleanup(home.close)
        installer.prepare(home)
        installer.own_home(home)
        done = installer.run(home, "--server")
        self.assertEqual(done.code, 0, done.out + done.err)
        # the Home's fakes lead the line's PATH too, as they lead everything else run in it
        local = home.path / ".local/bin"
        for fake in home.bin.iterdir():
            if not (local / fake.name).exists():
                (local / fake.name).symlink_to(fake)
        if keeper is not None:
            home.write(".agentkit/tmp/keep/ak", KEEPER.format(
                python=shlex.quote(sys.executable), code=keeper)).chmod(0o755)
        line, = [line for line in (home.root / "crontab").read_text().splitlines()
                 if line.endswith(" # agentkit watch")]
        # cron hands sh what follows the five time fields; the Home's paths hold no %, the one
        # character cron reads in it
        command = line.split(None, 5)[5]
        words = shlex.shlex(command, posix=True, punctuation_chars=True)
        path = next(word for word in words if word.startswith("PATH="))[len("PATH="):]
        home.run("/bin/sh", "-c", command, env={"PATH": "/usr/bin:/bin"})   # cron's own PATH
        log = home.path / ".agentkit/tmp/watch.log"
        said = log.read_text().splitlines() if log.exists() else []
        watch = home.path / ".agentkit/state/watch.json"
        tick = json.loads(watch.read_text()).get("tick") if watch.exists() else None
        self.assertIsNotNone(tick, said)
        return said, path, tick

    def test_with_the_link_the_keeper_runs_back_when_broken_then_the_tick(self):
        said, path, tick = self.cron(keeper=0)
        self.assertEqual(said[:2], ["back --when-broken", path])
        self.assertLessEqual(float(said[2]), tick["started_at"])

    def test_without_the_link_the_tick_runs(self):
        self.cron()

    def test_a_keeper_that_exits_1_still_has_the_tick_run_after_it(self):
        said, path, tick = self.cron(keeper=1)
        self.assertEqual(said[:2], ["back --when-broken", path])
        self.assertLessEqual(float(said[2]), tick["started_at"])


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
