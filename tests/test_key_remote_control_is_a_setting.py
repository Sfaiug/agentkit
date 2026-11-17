"""`remote_control = false` at the top of config.toml starts every seat without its harness's
Remote Control: a Claude seat's session still named after the seat (a Codex seat's:
tests/test_key_remote_control_off_on_codex.py).  `true`, or no such line, starts it with Remote
Control, a Claude seat's named after the seat; a value that is not a boolean is refused, naming
the key.

A seat's next launch follows the setting, so a new Claude seat and one reopened from its record
answer alike.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, whose fake `claude` refuses every call, and `ak orch --dry-run` prints
the line a Claude seat opens on.  This test fails against `/bin/false`.
"""

import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akseat import Seat

SEAT = "acme"


class RemoteControlIsASetting(unittest.TestCase):
    def launch(self, reopened, **settings):
        """What `ak orch --dry-run` answers for a new seat, or one reopened from its record,
        under a config.toml holding `settings` at its top."""
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"], settings=settings)
        if reopened:
            Seat(home, SEAT, alive=False)
            return home.ak("orch", SEAT, "--dry-run")
        return home.ak("orch", SEAT, "--model", "opus", "--dry-run")

    def claude(self, done):
        """The words the seat's line hands Claude Code: `claude` after the wrapper's `--`, on."""
        self.assertEqual(done.code, 0, done.out + done.err)
        words = shlex.split(done.out.splitlines()[-1])
        return words[words.index("claude", words.index("--")):]

    def test_off_names_the_session_after_the_seat_without_remote_control(self):
        for reopened in (False, True):
            with self.subTest(reopened=reopened):
                words = self.claude(self.launch(reopened, remote_control=False))
                self.assertNotIn("--remote-control", words)
                self.assertEqual(words[words.index("--name") + 1], SEAT)

    def test_on_or_unset_starts_remote_control_named_after_the_seat(self):
        for settings in ({"remote_control": True}, {}):
            for reopened in (False, True):
                with self.subTest(**settings, reopened=reopened):
                    words = self.claude(self.launch(reopened, **settings))
                    self.assertEqual(words[words.index("--remote-control") + 1], SEAT)
                    self.assertNotIn("--name", words)

    def test_a_value_that_is_not_a_boolean_is_refused_by_name(self):
        for reopened in (False, True):
            with self.subTest(reopened=reopened):
                done = self.launch(reopened, remote_control="no")
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertIn("remote_control", done.err)


if __name__ == "__main__":
    unittest.main()
