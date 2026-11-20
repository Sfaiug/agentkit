"""After a put-back no move of ~/agentkit starts until the seat told of it has its fix merged.

The commit put back had passed its live check, so the next commit to pass carries its fault.
`ak back` puts the last move back by hand on the Home tests/fixtures/akinstall.py makes, with the
seat that merged into agentkit at its prompt (`Install.seat`), and the next tick tells it.  A
newer commit whose tests/live.sh passes is then moved to by no tick, a merge of it by a run of
that seat launched before the put-back included, and `ak update` names the commit put back and
the seat in one line.  Once a run of that seat launched after the put-back, before the tick that
told it, records its merge at M, of the commit from before M and M itself, both passed, the tick
moves to M; from then on nothing is held: `ak update` names the put-back no more, and the next
commit that passes is moved to.  On a Home with no seat to tell, the first commit to pass after a
put-back is moved to at once.  A merged run is a record as a merge leaves one, its project with
no `health:`, the clone it ran in gone since.  Black-box, the whole file in one box
(`rerun_boxed`), as tests/test_key_a_put_back_is_handed_to_a_seat.py is; `ak update` reads a
claude manifest whose `[update]` names a binary no host has, so it upgrades nothing and goes
straight to ~/agentkit.  This test fails against `/bin/false`.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import BOXED, REAL_TMUX, Home, rerun_boxed
from fixtures.akinstall import Install

LIVE = "#!/bin/sh\nexit 0\n"
ABSENT = '[update]\nversion = ["ak-no-such-binary", "--version"]\nupgrade = ["ak-no-such-binary"]\n'


def wait(test, what, bound=180):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


@unittest.skipUnless(BOXED, "no bwrap able to box the test here")
class APutBackHoldsUntilItsFix(unittest.TestCase):
    def moved(self):
        """A Home whose tick moved ~/agentkit one commit on: the commit moved to."""
        self.home = home = self.enterContext(Home())
        # GitHub's kept answer, this host may push: its check is of origin's main
        home.write(".agentkit/state/agentkit-may-push", "true\n")
        akconfig.write(home, ["opus"])
        self.install = Install(home)
        self.before, after = self.install.head(), self.install.advance()
        self.tick()
        self.assertEqual(self.install.head(), after)
        return after

    def back(self):
        done = self.home.run(self.install.ak, "back", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.install.head(), self.before)

    def tick(self):
        done = self.home.run(self.install.ak, "watch", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)

    def push(self):
        """One more commit on origin's main, with a tests/live.sh that passes: its sha."""
        live = self.install.seed / "tests" / "live.sh"
        live.parent.mkdir(exist_ok=True)
        live.write_text(LIVE)
        return self.install.advance()

    def passed(self, commit):
        """The tick that starts `commit`'s live check, and that check's end."""
        self.tick()
        checks = self.home.path / ".agentkit" / "state" / "live-checks"
        wait(lambda: any((check / "exit").exists() for check in checks.glob(f"{commit}-*")),
             f"{commit[:12]}'s live check")

    def update(self):
        """What `ak update` says."""
        adapters = self.home.root / "adapters"
        adapters.mkdir(exist_ok=True)
        (adapters / "claude.toml").write_text(ABSENT)
        done = self.home.ak("update", env={"AGENTKIT_ADAPTER_DIR": str(adapters)}, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out.splitlines()

    def merged(self, pr, seat, commit, started):
        """A run that `seat` launched at `started`, its PR `pr` merged into acme/agentkit at
        `commit`."""
        run = f"20261114-1600-agentkit-fix-{pr}-{seat}"
        self.home.write(f".agentkit/runs/{run}/run.json", {
            "run_id": run, "state": "pass", "verdict": "PASS", "merged": True,
            "merge_sha": commit, "health": {}, "deployed": None,
            "started_at": started, "finished_at": time.time(),
            "repo": str(self.home.root / "gone"),
            "pr": f"https://github.com/acme/agentkit/pull/{pr}", "launched_session": seat})

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_no_move_starts_until_the_told_seat_s_fix_has_merged(self):
        put_back = self.moved()
        seat = self.install.seat()
        early = time.time() - 3600     # before the seat's own run too: its earliest merged
        self.back()
        since = time.time()     # after the put-back, before the tick that tells the seat
        self.tick()
        wait(lambda: any(put_back[:12] in line for line in seat.lines()), "the put-back's line")

        first = self.push()
        self.passed(first)
        self.merged(2, seat.name, first, early)
        self.tick()
        self.assertEqual(self.install.head(), self.before)
        self.assertTrue([line for line in self.update()
                         if put_back[:12] in line and seat.name in line])
        self.assertEqual(self.install.head(), self.before)

        fix = self.push()
        self.passed(fix)
        self.tick()
        self.assertEqual(self.install.head(), self.before)    # no run since merged it yet
        self.merged(3, seat.name, fix, since)
        self.tick()
        self.assertEqual(self.install.head(), fix)

        self.tick()     # a tick of the version moved to: the move is final
        last = self.push()
        self.assertEqual([line for line in self.update() if put_back[:12] in line], [])
        self.passed(last)
        self.tick()
        self.assertEqual(self.install.head(), last)

    def test_with_no_seat_the_next_commit_to_pass_is_moved_to(self):
        self.moved()
        self.back()
        first = self.push()
        self.passed(first)
        self.tick()
        self.assertEqual(self.install.head(), first)


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
