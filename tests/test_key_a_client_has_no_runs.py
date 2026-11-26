"""A client has no runs: on a machine whose server record (`state/server`) names a home,
`ak run status`, `ak run resume ID`, `ak run merge ID`, `ak run stop ID`, `ak run TASK.md` and
`ak run gc` each exit 2 naming that home on stderr, open no session, and leave a run's record there
byte for byte as it was, one interrupted a month ago whose process is gone; the version of ak that
record names (`ak_checkout`) answers none of them.  Without the server record `ak run status`
exits 0.

A standby holds a copy of its home's run records and none of their processes.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable

RUN = "20260101-0000-fix-api"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClientHasNoRuns(unittest.TestCase):
    def refused(self, *commands, boxed=False):
        """Each of `commands` after `ak run` exits 2 naming the home, leaves the record byte for
        byte as it was and opens no session."""
        with Home() as home:
            akconfig.write(home, ["opus"])
            # the version the run was launched on, older than this refusal: its bin/ak exits 0
            home.write("old-ak/bin/ak", "")
            record = home.write(f".agentkit/runs/{RUN}/run.json",
                                {"run_id": RUN, "state": "interrupted", "pid": 2147483647,
                                 "started_at": 1, "interrupted_at": 1,
                                 "ak_checkout": str(home.path / "old-ak")})
            home.write("fix-api.md", "# Fix the api\n")
            home.write(".agentkit/state/server", "acme-box\n")
            before = record.read_bytes()
            for args in commands:
                done = home.ak("run", *args, input="", boxed=boxed)
                self.assertEqual(done.code, 2, (args, done.out, done.err))
                self.assertIn("acme-box", done.err, args)
            self.assertEqual(record.read_bytes(), before)
            self.assertEqual(home.tmux("list-sessions", "-F", "#{session_name}").out.split(), [])

    def test_each_command_names_the_home_and_touches_nothing(self):
        self.refused(["status"], ["resume", RUN], ["merge", RUN], ["stop", RUN], ["fix-api.md"])

    # a collection that runs sweeps /tmp: the box gives it one holding only this Home
    @unittest.skipUnless(boxable(), "no bwrap able to give the collection a /tmp of its own")
    def test_collection_takes_nothing(self):
        self.refused(["gc"], boxed=True)

    def test_without_the_record_status_answers(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            self.assertEqual(home.ak("run", "status", input="").code, 0)


if __name__ == "__main__":
    unittest.main()
