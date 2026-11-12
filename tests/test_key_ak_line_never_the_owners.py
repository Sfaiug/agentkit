"""A line ak types into a seat is never read as the owner's, whichever of the seat's
conversations it went into.  In Grok session A the owner asks for a retry button and a receipt
email, opens B with /new and says "thanks" there; the screen shows A again, as /dashboard
switches it with no hook, while the record still names B, so ak's typing receipt names B.  The
line ak's tick types lands in A.  The plan holds the button alone, every line done: `ak orch
check` names the email, and its workspace's owner/ holds no file with ak's line, until the owner
types those very words in A themselves, which one file then holds.  Black-box on `AK_BIN`, with
the fake `grok` and model of test_key_grok_new_session_followed.py.
"""

import shlex
import unittest

from test_key_grok_new_session_followed import A, LINE, SECOND, GrokSeat
from fixtures.akbin import boxable


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class AkLineNeverTheOwners(GrokSeat):
    def owner_files_holding_line(self):
        """`ak orch check` names the email gap: the files of its workspace's owner/ holding LINE."""
        kept = self.fake.dir / "owner"
        self.fake.behave({**self.gap, "sh": f"rm -rf {shlex.quote(str(kept))}; "
                                            f"cp -r owner {shlex.quote(str(kept))}; {self.gap['sh']}"})
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)
        return [path.name for path in kept.iterdir() if LINE in path.read_text()]

    def test_ak_s_line_in_the_session_shown_is_not_the_owner_s_but_their_own_words_are(self):
        self.ak_types_into_a()
        self.assertEqual(self.record()["conversation"], A)
        self.assertEqual(self.owner_files_holding_line(), [])
        self.assertEqual(self.type(LINE), A)
        self.assertEqual(len(self.owner_files_holding_line()), 1)


if __name__ == "__main__":
    unittest.main()
