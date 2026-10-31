"""Asked for subscriptions, agentkit/lend.py lends a harness whose usual login has none to lend
the first subscription the caller's config lists, on a provider it runs, that has one, and says
which; not asked, it lends as it always did.

Through the module, in-process and on its command line, and the real adapters, from a caller
HOME of fixture logins holding fake values beside a config, with every harness program faked,
as tests/test_checks_lend_logins_that_cannot_renew.py does.  The config lists Google's
subscriptions and runs none of its models, so only the shipped default says Google runs on
Antigravity; Antigravity's own `auth`, run on the HOME lent, says which turns read the copy.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_checks_lend_logins_that_cannot_renew import LENT, REPO, LentLogins
from agentkit import config, lend

CONFIG = """[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "xhigh"
provider = "anthropic"

[providers.anthropic]
mode = "subscription"

[providers.google]
mode = "subscription"
accounts = {}
"""


def place(account):
    """Where that account's Antigravity login lives under HOME, the usual one's for ""."""
    return f".gemini/antigravity-cli{account and '-' + account}/antigravity-oauth-token"


class LendAListedSubscription(LentLogins):
    def holds(self, accounts, logins):
        """The caller's config listing Google's `accounts`, and its Antigravity logins those of
        the accounts in `logins` alone, "" the usual one."""
        path = self.caller / ".agentkit/config.toml"
        path.parent.mkdir(parents=True)
        path.write_text(CONFIG.format(json.dumps(accounts)))
        (self.caller / place("")).unlink()
        for account in logins:
            path = self.caller / place(account)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"token": {"refresh_token": f"fixture-{account}"}}))

    def lend(self, *flag):
        """What the module lends the caller, `flag` on its command line and `subscriptions` its
        keyword where given: the HOME `into` lent, what it returned, and the lines printed."""
        home, printed = self.root / "lent", self.root / "printed"
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(config, "HOME", self.caller / ".agentkit"):
            returned = lend.into(home, subscriptions=True) if flag else lend.into(home)
        proc = subprocess.run([sys.executable, "-m", "agentkit.lend", *flag, str(printed)],
                              env={**self.env, "PYTHONPATH": str(REPO)}, text=True,
                              capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [" ".join([harness, *(str(path.relative_to(home)) for path in files)])
                 for harness, files in returned[0].items()]
        self.assertEqual(proc.stdout.splitlines()[:len(lines)], lines)
        return home, returned, proc.stdout.splitlines()[len(lines):]

    def auth(self, home, account):
        """Antigravity's `auth` exit code, run with HOME=`home` and `account` named."""
        env = {**self.env, "HOME": str(home), "AGENTKIT_ACCOUNT": account}
        return subprocess.run(["bash", str(REPO / "adapters/antigravity.sh"), "auth"], env=env,
                              capture_output=True, timeout=60).returncode

    def assert_said(self, returned, said, named):
        self.assertEqual(returned[2], named)
        self.assertEqual([json.loads(line) for line in said], [named])

    def test_a_named_account_alone_is_lent_where_its_turns_read_it(self):
        self.holds(["acme"], ["acme"])
        home, returned, said = self.lend("--subscriptions")
        self.assertEqual(self.auth(home, "acme"), 0)
        self.assertEqual(self.auth(home, ""), 1)
        self.assertIn(home / place("acme"), returned[0]["antigravity"])
        self.assert_said(returned, said, {"google": "acme"})

    def test_a_listed_account_with_no_login_gives_way_to_the_next(self):
        self.holds(["acme", "globex"], ["globex"])
        home, returned, said = self.lend("--subscriptions")
        self.assertEqual(self.auth(home, "globex"), 0)
        self.assert_said(returned, said, {"google": "globex"})

    def test_the_usual_login_is_lent_before_any_listed(self):
        self.holds(["acme"], ["", "acme"])
        home, returned, said = self.lend("--subscriptions")
        self.assertEqual(self.auth(home, ""), 0)
        self.assertEqual(returned[0]["antigravity"], [home / place("")])
        self.assert_said(returned, said, {})

    def test_a_config_that_cannot_be_read_lists_none(self):
        self.holds(["acme"], ["acme"])
        (self.caller / ".agentkit/config.toml").write_text("[providers.google\n")
        _, returned, said = self.lend("--subscriptions")
        self.assertNotIn("antigravity", returned[0])
        self.assert_said(returned, said, {})

    def test_not_asked_it_lends_the_usual_logins_alone(self):
        self.holds(["acme"], ["acme"])
        home, returned, said = self.lend()
        self.assertEqual(len(returned), 2)
        self.assertEqual(said, [])
        self.assertNotIn("antigravity", returned[0])
        self.assertEqual({str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()},
                         LENT - {place("")})


if __name__ == "__main__":
    unittest.main()
