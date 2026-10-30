"""`ak worker` exits as its adapter's command did, and its line names the code where it is not 0.

A turn runs its adapter in a box, whose own first process reports how the command ended, so
nothing about the box shows in the status: an exit of N is N, 137 and 143 among them, never
taken for a death by signal, and a command killed by a signal keeps that death's status.  A
command that cannot start keeps the shell's codes: 127 where its interpreter is missing, 126
where it is no program at all.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, with a config from akconfig.py and a scripted harness from
fakeadapter.py, whose `sh` step ends the adapter itself.
"""

import signal
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home, boxable


@unittest.skipUnless(boxable(), "no bwrap able to box a turn here")
class WorkerExitStatus(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {"beta": {"harness": "acme", "model": "beta-1",
                                            "effort": "low"}})
        self.fake = fakeadapter.install(self.home, acme="pass")["acme"]
        self.ws = self.home.path / "code" / "widgets"
        self.ws.mkdir(parents=True)
        self.task = self.home.write("fix-api.md", "Fix the parser.\n")

    def assertExits(self, code):
        """One `ak worker beta` exits with `code`, its line naming it where it is not 0."""
        out = self.home.path / "out"
        done = self.home.ak("worker", "beta", str(self.task), "--workspace", str(self.ws),
                            "--out", str(out))
        self.assertEqual((done.code, done.out), (code % 256, f"{out}/final.md\n"), done.err)
        if code:
            self.assertIn(f"ak worker: beta exited {code}; see {out}/stderr.log", done.err)

    def test_an_exit_of_n_is_n(self):
        for code in (0, 3, 137, 143):
            with self.subTest(code=code):
                self.fake.behave({"exit": code})
                self.assertExits(code)

    def test_a_command_killed_by_a_signal_keeps_that_death_s_status(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=sig.name):
                # the step's shell is the adapter's child: $PPID is the adapter itself
                self.fake.behave({"sh": f"kill -{sig.name[3:]} $PPID"})
                self.assertExits(-sig)

    def test_a_command_that_cannot_start_keeps_the_shell_s_code(self):
        for text, code in (("#!/nonexistent/sh\n", 127), ("no program\n", 126)):
            with self.subTest(code=code):
                self.fake.script.write_text(text)
                self.assertExits(code)


if __name__ == "__main__":
    unittest.main()
