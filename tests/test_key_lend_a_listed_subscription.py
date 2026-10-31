"""`python3 -m agentkit.lend --subscriptions <home>` lends a harness whose usual login has none
to lend the first subscription its HOME's config lists, where a turn naming that account reads
it, and prints the JSON {provider: account} of what it lent so last; without the flag it lends
the usual logins alone, as ever.

Black-box: the module of the checkout beside the program `AK_BIN` names, as
tests/fixtures/hookdrive.py finds it, run in a Home of tests/fixtures/akbin.py whose only login
is Antigravity's under a Google account `acme` its config lists, with every harness program a
manifest names, and macOS's Keychain, faked to fail: OpenCode's answers that it merges no other
config document and saved no login.
"""

import json
from pathlib import Path
import sys
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

LOGIN = ".gemini/antigravity-cli-acme/antigravity-oauth-token"
OPENCODE = """case "$*" in "api --standalone config.get"|"auth export --standalone") echo '[]'; exit 0 ;; esac
"""


class LendAListedSubscription(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        for path in sorted((ROOT / "adapters").glob("*.toml")):
            program = tomllib.loads(path.read_text())["update"]["version"][0]
            self.home.fake(program, "#!/bin/sh\n" + (OPENCODE if path.stem == "opencode" else "")
                           + "exit 97\n")
        self.home.fake("security", "#!/bin/sh\nexit 1\n")
        config = self.home.path / ".agentkit/config.toml"
        config.write_text(config.read_text().replace(
            '[providers.google]\n', '[providers.google]\naccounts = ["acme"]\n'))
        self.home.write(LOGIN, {"token": {"refresh_token": "fixture-acme"}})

    def lend(self, *flag):
        """What the module did lending this Home into an empty <home>, and that <home>."""
        lent = self.home.root / "lent"
        return self.home.run(sys.executable, "-m", "agentkit.lend", *flag, str(lent),
                             env={"PYTHONPATH": str(ROOT)}), lent

    def test_asked_it_lends_the_listed_account_and_says_so(self):
        done, lent = self.lend("--subscriptions")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines(),
                         [f"antigravity {LOGIN}", json.dumps({"google": "acme"})])
        self.assertEqual(json.loads((lent / LOGIN).read_text()),
                         {"token": {"refresh_token": "fixture-acme"}})

    def test_not_asked_it_lends_no_named_account(self):
        done, lent = self.lend()
        self.assertEqual((done.code, done.out), (0, ""), done.err)
        self.assertEqual([path for path in lent.rglob("*") if path.is_file()], [])


if __name__ == "__main__":
    unittest.main()
