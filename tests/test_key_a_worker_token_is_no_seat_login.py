"""A saved worker token says nothing about a seat's login: no seat runs on one.

Claude Code's long-lived worker token signs a turn in and never a seat, so `auth seat` answers
from what is saved for the seat alone, in the Keychain or the credentials file.  A check reads
its one line to tell a login this host lacks, which it leaves out, from a saved one that is
broken, which fails it (tests/test_a_worker_token_is_no_seat_login.py).  Beside the token and
nothing else the line says no credentials are saved, naming the file that is not there.  Beside
a Keychain entry that names no access token, or one whose password cannot be read, it says the
saved credentials carry none.

Black-box: the adapter beside the program `AK_BIN` names (or `AK_ROOT`'s) runs as ak runs it, in
a Home of tests/fixtures/akbin.py holding the token, with a `security` of the case's own; this
test fails against `/bin/false`.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home  # noqa: E402
from test_key_auth_reads_login import CREDS, NO_KEYCHAIN, NO_LOGIN, TOKEN, ask  # noqa: E402

# What `auth seat` says of credentials that are saved and cannot sign a seat in.
NO_TOKEN = (1, f"claude: the credentials in ~/{CREDS} carry no access token; run /login")
# A Keychain holding an entry that names no access token, and one whose entry is found and
# whose password (`-w`) is refused.
KEYLESS = """#!/bin/sh\necho '{"claudeAiOauth": {"refreshToken": "acme-refresh"}}'\n"""
UNREADABLE = '#!/bin/sh\nfor arg do [ "$arg" != -w ] || exit 36; done\necho "class: genp"\n'


class AWorkerTokenIsNoSeatLogin(unittest.TestCase):
    def says(self, answer, keychain=NO_KEYCHAIN):
        """Beside a worker token and the Keychain the script `keychain` plays, `auth seat`
        answers `answer`: its code and its one line, with ~ for HOME."""
        with Home() as home:
            # No HOME hides a Mac's Keychain: the host's own login there would answer for a seat.
            home.fake("security", keychain)
            home.write(TOKEN, "acme-worker\n")
            code, line = answer
            self.assertEqual(ask(home, "claude", ("auth", "seat"), None),
                             (code, [line.replace("~/", f"{home.path}/")]))

    def test_beside_only_a_worker_token_no_credentials_are_saved(self):
        self.says(NO_LOGIN)

    def test_a_keychain_entry_naming_no_access_token_is_saved_and_carries_none(self):
        self.says(NO_TOKEN, KEYLESS)

    def test_a_keychain_entry_whose_password_cannot_be_read_is_saved_and_carries_none(self):
        self.says(NO_TOKEN, UNREADABLE)


if __name__ == "__main__":
    unittest.main()
