"""`adapters/<harness>.sh lend <home> own` puts a named account's login where its own turns read it.

ak's live check runs a subscription that has no usual login the way ak's turns on this host run
it, with its account named, so the adapter's own handling of that account applies; `lend <home>`
alone still puts the copy where a turn naming no account reads it, as a machine turn runs it.
Each adapter whose manifest's `[worker] logins` names a login per account runs on a temporary
HOME holding fixture logins of fake values, the usual one's and an account `acme`'s, with a fake
of every harness program and of macOS's Keychain; its own `auth`, run with HOME=<home>, says
which turns read the copy.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_lend_key
import test_lend_login

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = test_lend_key.MANIFESTS
PER_ACCOUNT = [harness for harness, data in MANIFESTS.items()
               if any("$AGENTKIT_ACCOUNT" in path
                      for path in data.get("worker", {}).get("logins", []))]


def place(harness, account):
    """Where that account's login lives under HOME as the manifest names it, the usual one's
    for none."""
    logins = MANIFESTS[harness]["worker"]["logins"]
    path = (next(path for path in logins if "$AGENTKIT_ACCOUNT" in path) if account
            else next(path for path in logins if "$" not in path))
    return path.removeprefix("~/").replace("$AGENTKIT_ACCOUNT", account)


def login(harness, key):
    """That harness's unexpired fixture login around `key`, as the tests of `lend` keep it."""
    if harness in test_lend_login.LOGINS:
        return test_lend_login.LOGINS[harness]["login"](key, test_lend_login.ENDS)
    return test_lend_key.LOGINS[harness]["login"](key)


class LendOwn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        # every harness program a manifest names, and macOS's Keychain, which no HOME hides:
        # each fails, so no real login is reached
        fakes = self.root / "bin"
        fakes.mkdir()
        for name in {data["update"]["version"][0] for data in MANIFESTS.values()} | {"security"}:
            (fakes / name).write_text("#!/bin/sh\nexit 97\n")
            (fakes / name).chmod(0o755)
        self.path = f"{fakes}{os.pathsep}{os.environ['PATH']}"

    def adapter(self, harness, home, account, *args):
        """That adapter's exit code for `args`, run with HOME=`home` and `account` named."""
        env = {"HOME": str(home), "PATH": self.path, "AGENTKIT_ACCOUNT": account}
        return subprocess.run(["bash", str(REPO / f"adapters/{harness}.sh"), *args], env=env,
                              capture_output=True, timeout=60).returncode

    def lend(self, harness, *own):
        """acme's login lent from a HOME holding it beside the usual one: the HOME lent into,
        and each login's key by its account."""
        host, home = (Path(tempfile.mkdtemp(dir=self.root)) for _ in range(2))
        keys = {}
        for account in ("", "acme"):
            keys[account] = test_lend_login.jwt({"exp": test_lend_login.ENDS,
                                                 "sub": f"{harness}-{account or 'usual'}"})
            path = host / place(harness, account)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(login(harness, keys[account])))
        self.assertEqual(self.adapter(harness, host, "acme", "lend", str(home), *own), 0)
        return home, keys

    def test_own_puts_it_where_a_turn_naming_the_account_reads_it(self):
        for harness in PER_ACCOUNT:
            with self.subTest(harness=harness):
                home, keys = self.lend(harness, "own")
                self.assertEqual(self.adapter(harness, home, "acme", "auth"), 0)
                self.assertEqual(self.adapter(harness, home, "", "auth"), 1)
                copy = (home / place(harness, "acme")).read_text()
                self.assertIn(keys["acme"], copy)
                self.assertNotIn(keys[""], copy)

    def test_without_own_a_turn_naming_no_account_reads_it(self):
        for harness in PER_ACCOUNT:
            with self.subTest(harness=harness):
                home, _ = self.lend(harness)
                self.assertEqual(self.adapter(harness, home, "", "auth"), 0)


if __name__ == "__main__":
    unittest.main()
