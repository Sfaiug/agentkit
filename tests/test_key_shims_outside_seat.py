"""For a worker, and outside any seat, every shim is the real tool and changes nothing.

The shims guard a seat's own commands.  A worker runs the same tools on the same PATH, and so does
ak's own seatless work (its merges, its checkouts); a shim that refused, rewrote or tagged their
calls would break that work.  For them a copy onto the live host, a `gh pr merge` and a checkout
in ~/code reach the real tool as typed, its output and exit code come back, and what tmux starts
for them speaks for no seat.  Ending another seat's session from there is pinned by
tests/test_key_tmux_shim_other_seat.py.  Black-box: the shims a seat's launch installs
(tests/fixtures/shims.py), with logging fakes as the real scp, rsync, gh and git and the Home's
real tmux, judged by exit codes, output, the fakes' calls and the environment of what tmux
started; this test fails against `/bin/false`.
"""

from itertools import product
import json
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat
from fixtures.shims import Shims

CALLERS = (("a worker", "acme", {"AK_RUN_ROLE": "worker"}), ("no seat", None, None))
# What a started process's environment holds, written whole once it is read.
DUMP = ("import json, os, pathlib, sys; part = pathlib.Path(sys.argv[1] + '.part'); "
        "part.write_text(json.dumps(dict(os.environ))); part.replace(sys.argv[1])")
SPEAKS = {"AGENTKIT_SESSION", "AK_TMUX_OWNER"}      # what names a seat to a process tmux starts


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OutsideASeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)
        Seat(cls.home, "acme", alive=False)
        for tool in ("scp", "gh", "git"):
            cls.shims.fake(tool, out=f"{tool} ran\n")
        cls.shims.fake("rsync", code=23, out="rsync: some files were not transferred\n")
        config = cls.home.path / ".agentkit" / "config.toml"
        config.write_text(f'live_host = "prod"\n{config.read_text()}')
        # a session ak keeps no record of, to open windows in
        done = cls.home.tmux("new-session", "-d", "-s", "scratch", "sleep 600")
        assert done.code == 0, done.err

    def test_what_a_seat_may_not_run_reaches_the_real_tool_as_typed(self):
        code = str(self.home.path / "code" / "fix-api")
        for (who, seat, env), argv in product(CALLERS, (("scp", "a.txt", "prod:/srv/"),
                                                        ("gh", "pr", "merge", "7"),
                                                        ("git", "worktree", "add", code))):
            with self.subTest(who, argv=argv):
                done = self.shims.run(*argv, seat=seat, env=env)
                self.assertEqual((done.code, done.out, done.err), (0, f"{argv[0]} ran\n", ""))
                self.assertEqual(self.home.calls(argv[0])[-1], list(argv[1:]))

    def test_the_real_tools_failure_comes_back_as_its_own(self):
        for who, seat, env in CALLERS:
            with self.subTest(who):
                done = self.shims.run("rsync", "-a", "x/", "prod:/srv/x/", seat=seat, env=env)
                self.assertEqual((done.code, done.out, done.err),
                                 (23, "rsync: some files were not transferred\n", ""))
                self.assertEqual(self.home.calls("rsync")[-1], ["-a", "x/", "prod:/srv/x/"])

    def test_what_tmux_starts_for_them_speaks_for_no_seat(self):
        for n, (who, seat, env) in enumerate(CALLERS):
            for start in (("new-window", "-d", "-t", "=scratch:"),
                          ("new-session", "-d", "-s", f"fix-api-{n}")):
                with self.subTest(who, start=start[0]):
                    dump = self.home.root / f"env-{n}-{start[0]}.json"
                    command = shlex.join([sys.executable, "-c", DUMP, str(dump)])
                    done = self.shims.run("tmux", "-L", SOCKET, *start, command, seat=seat,
                                          env=env)
                    self.assertEqual(done.code, 0, done.err)
                    self.assertEqual(SPEAKS & set(self.environment(dump)), set())

    def environment(self, dump, bound=30):
        """The environment the started process ran with, once it has written it."""
        deadline = time.monotonic() + bound
        while not dump.exists():
            if time.monotonic() > deadline:
                raise AssertionError(f"what tmux started never ran: {dump.name}")
            time.sleep(0.05)
        return json.loads(dump.read_text())


if __name__ == "__main__":
    unittest.main()
