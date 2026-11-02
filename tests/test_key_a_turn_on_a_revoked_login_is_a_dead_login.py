"""A Claude turn whose login was revoked says so only in its result, and a worker reads it there.

A renewal revokes the login it replaces at once, so a turn still holding the old one ends with
those words on stdout and nothing on stderr. It is a dead login, not a failed turn, so the adapter
leaves them in stderr.log, where a worker reads a harness's `[auth] signatures`
(tests/test_key_worker_auth_expired.py). Black-box: the adapter beside the program `AK_BIN` names,
in a Home of tests/fixtures/akbin.py, with a stand-in for Claude Code. Fails against `/bin/false`.
"""

from pathlib import Path
import sys
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

SAID = "Failed to authenticate: OAuth token revoked. Please log in again or contact your administrator."
RESULT = '{"type":"result","is_error":%s,"result":"%s","session_id":"s-1"}'


class RevokedLogin(unittest.TestCase):
    def stderr_log(self, is_error, code):
        with Home() as home:
            home.fake("claude", f"#!/bin/bash\ncat >/dev/null\necho '{RESULT % (is_error, SAID)}'\nexit {code}\n")
            prompt, out = home.write("prompt.md", "Fix the api.\n"), home.path / "out"
            done = home.run(str(ROOT / "adapters/claude.sh"), "run", "m-1", "high", str(home.path),
                            str(prompt), str(out))
            self.assertEqual(done.code, code, done.err)
            return (out / "stderr.log").read_text()

    def test_a_failed_turn_leaves_the_words_its_result_ended_on_where_a_worker_reads(self):
        self.assertEqual(self.stderr_log("true", 1).strip(), SAID)
        signatures = tomllib.loads((ROOT / "adapters/claude.toml").read_text())["auth"]["signatures"]
        self.assertIn(SAID, signatures)

    def test_a_turn_that_passed_leaves_nothing_there(self):
        self.assertEqual(self.stderr_log("false", 0), "")


if __name__ == "__main__":
    unittest.main()
