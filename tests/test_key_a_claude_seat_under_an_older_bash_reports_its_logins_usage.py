"""A Claude seat under a bash without bash 5's `$EPOCHREALTIME` (macOS's 3.2) reports its login's
usage as one under bash 5 does, at the moment perl's Time::HiRes gives; under bash 5 it starts no
perl.

Black-box against AK_BIN: tests/test_key_a_claude_seat_reports_its_logins_usage.py's renders,
with a fake `perl` first on PATH that logs each answer of the host's own.  Under the older bash,
a `BASH_ENV` that unsets the clock in each bash the Home starts, the reading that changed is at
one of perl's moments.  This test fails against `/bin/false`.
"""

import shlex
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM
import test_key_a_claude_seat_reports_its_logins_usage as bash5

PERL = shutil.which("perl", path=":".join(SYSTEM))


class Perl:
    def setUp(self):
        if PERL is None:
            self.skipTest("no perl on this host")
        super().setUp()
        self.answers = self.home.root / "perl.log"
        self.home.fake("perl", f"#!/bin/sh\nanswer=$({shlex.quote(PERL)} \"$@\") || exit\n"
                               f"printf '%s\\n' \"$answer\" >>{shlex.quote(str(self.answers))}\n"
                               "printf %s \"$answer\"\n")

    def answered(self):
        return self.answers.read_text().splitlines() if self.answers.exists() else []


class UnderAnOlderBash(Perl, bash5.ClaudeSeatReportsItsLoginsUsage):
    def setUp(self):
        super().setUp()
        self.home.env["BASH_ENV"] = str(self.home.write("older-bash.sh", "unset EPOCHREALTIME\n"))

    def test_only_a_conversations_changed_numbers_are_its_logins_reading(self):
        super().test_only_a_conversations_changed_numbers_are_its_logins_reading()
        moments = [meter["measured_at"] for meter in self.reading()["meters"]
                   if meter["name"] == "weekly_all"]
        self.assertEqual(len(moments), 1)
        self.assertIn(moments[0], [float(answer) for answer in self.answered()])


class UnderBash5(Perl, bash5.ClaudeSeatReportsItsLoginsUsage):
    def test_only_a_conversations_changed_numbers_are_its_logins_reading(self):
        super().test_only_a_conversations_changed_numbers_are_its_logins_reading()
        self.assertEqual(self.answered(), [], "a render under bash 5 started perl")


if __name__ == "__main__":
    unittest.main()
