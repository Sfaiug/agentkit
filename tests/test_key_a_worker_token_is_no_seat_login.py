"""A saved worker token says nothing about a seat's login: no seat runs on one.

A live check asks smoke.sh's `model_unavailable` about each model it needs: a reason with exit 0
leaves the check out, the harness not on this host, and exit 1 fails it, the saved login broken.
Claude Code's long-lived worker token signs a turn in and never a seat, so a host holding only
that token has no seat login: missing, not broken.  What is saved for the seat decides: beside
that token, a Keychain entry that carries no access token is a broken login.  A worker's
question still reads a token past its year as broken.

Black-box: `model_unavailable` as smoke.sh holds it asks, in a Home of tests/fixtures/akbin.py;
only its exit code and whether it gave a reason count.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REPO, Home  # noqa: E402

SMOKE = (REPO / "tests/smoke.sh").read_text()
ASK = SMOKE[SMOKE.index("model_unavailable()"):SMOKE.index("skip_unavailable()")]
DAY = 86400
# What smoke.sh reads of the answer: its exit code, and whether it gave a reason.
MISSING, BROKEN = (0, True), (1, True)
# What a Keychain says of a saved login that carries no access token.
KEYLESS ="""echo '{"claudeAiOauth": {"refreshToken": "acme-refresh"}}'"""


class AWorkerTokenIsNoSeatLogin(unittest.TestCase):
    def reads(self, read, *seat, token_age=0, keychain="exit 1"):
        """smoke.sh reads `read` of its question about Claude Code's login, a worker's or with
        "seat" the seat's, on a host holding a worker token `token_age` days old and the Keychain
        the script `keychain` plays, by default one holding nothing."""
        with Home() as home:
            # No HOME hides a Mac's Keychain: the host's own login there would answer for a seat.
            home.fake("security", f"#!/bin/sh\n{keychain}\n")
            home.write(".agentkit/secrets/claude_oauth_token", "acme-worker\n",
                       ago=token_age * DAY)
            done = home.run("/bin/bash", "-c", f"{ASK}\nmodel_unavailable opus {' '.join(seat)}",
                            env={"REPO": str(REPO)})
            self.assertEqual((done.code, bool(done.out.strip())), read, done.out + done.err)

    def test_a_seat_beside_only_a_worker_token_has_no_login_and_no_broken_one(self):
        self.reads(MISSING, "seat")

    def test_a_seat_whose_saved_login_carries_no_access_token_has_a_broken_one(self):
        self.reads(BROKEN, "seat", keychain=KEYLESS)

    def test_a_worker_whose_token_is_past_its_year_has_a_broken_login(self):
        self.reads(BROKEN, token_age=366)


if __name__ == "__main__":
    unittest.main()
