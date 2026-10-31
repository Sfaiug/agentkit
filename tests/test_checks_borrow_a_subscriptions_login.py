"""ak's live check runs a harness whose only login is a subscription its caller's config lists
by name on that subscription, its account named, and counts it there; a usual login still goes
first, and then nothing is named.

Through smoke_home's own code, check 3's and agentkit/lend.py, from a caller HOME of fixture
logins holding fake values, with every harness program faked, as
tests/test_checks_lend_logins_that_cannot_renew.py does.  The caller's config lists the account
`acme` for one provider and runs none of its models.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_checks_lend_logins_that_cannot_renew import LentLogins, REPO, SMOKE
from test_lend_a_listed_subscription import place
from test_update_gate_every_harness import unboxed_worker
from agentkit import config
import check4_pair

CONFIG = """[models.grok]
harness = "grokbuild"
model = "grok-4"
effort = "high"
provider = "xai"

[providers.xai]
mode = "subscription"

[providers.{}]
mode = "subscription"
accounts = ["acme"]
"""
SETUP = SMOKE[SMOKE.index("smoke_share_probes() {"):SMOKE.index("# A bounded way")]
READINGS = {"default": {"meters": [], "error": "the usual login's"},
            "acme": {"meters": [], "error": "acme's"}}
# Says which credential it was given, runs the prompt's `Run:` lines and, resumed, names the
# file they made, as Claude's stream does.
CLAUDE = """#!/bin/bash
creds=${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.credentials.json
echo "${CLAUDE_CODE_OAUTH_TOKEN:-$(jq -r .claudeAiOauth.accessToken "$creds")}" >>"$SPENT"
prompt=$(cat)
case " $* " in
  *" --resume "*) said=$(cat "$SPENT.made") ;;
  *) sed -n 's/^Run: //p' <<<"$prompt" | sh
     sed -n 's/^Run: printf .* > //p' <<<"$prompt" >"$SPENT.made"; said=DONE ;;
esac
printf '{"type":"result","result":"%s","session_id":"fixture-session"}\\n' "$said"
"""


class ChecksBorrowASubscriptionsLogin(LentLogins):
    def smoke(self, provider, usual, own, keep=False, **env):
        """The HOME smoke_home makes for a caller whose config lists `acme` for `provider`, and
        whose login at `usual` is at `own`, acme's place, instead, or there too with `keep`."""
        (self.caller / ".agentkit").mkdir(exist_ok=True)
        (self.caller / ".agentkit/config.toml").write_text(CONFIG.format(provider))
        (self.caller / own).parent.mkdir(parents=True)
        (self.caller / own).write_bytes((self.caller / usual).read_bytes())
        if not keep:
            (self.caller / usual).unlink()
        self.env.update(env)
        result = subprocess.run(["/bin/bash", "-c", SETUP + "\nsmoke_home\n"],
                                env={**self.env, "WORK": str(self.root / "smoke")},
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.root / "smoke/home"

    def assert_counted(self, home, account):
        """Antigravity's login there is `account`'s, "" the usual one, and the check counts
        Google on it: its config lists that account, its probe files are the host's for that
        login, and `providers` reads that login's host reading."""
        self.assertEqual([path.relative_to(home) for path in home.rglob("antigravity-oauth-token")],
                         [Path(place(account))])
        with patch.object(config, "HOME", home / ".agentkit"):
            cfg = config.load()
        self.assertEqual(config.accounts(cfg, "google"), [account] if account else [])
        host = self.caller / ".agentkit/state"
        self.assertEqual({path.name: os.readlink(path)
                          for path in (home / ".agentkit/state").glob("google*")},
                         {f"google{account and '.' + account}-probe.{end}":
                          str(host / f"google.{account or 'default'}-probe.{end}")
                          for end in ("lock", "retry")})
        (host / "usage.json").write_text(json.dumps(
            {"providers": {"google": {"account": "acme", "accounts": READINGS}}}))
        self.assertEqual(check4_pair.providers(cfg, host / "usage.json")["google"],
                         READINGS[account or "default"])

    def test_a_listed_account_alone_is_lent_and_counted_by_name(self):
        self.assert_counted(self.smoke("google", place(""), place("acme")), "acme")

    def test_a_usual_login_beside_a_listed_one_is_lent_and_counted_as_ever(self):
        self.assert_counted(self.smoke("google", place(""), place("acme"), keep=True), "")

    def test_check_3_spends_the_listed_account_not_the_usual_tokens(self):
        token = self.caller / ".agentkit/secrets/claude_oauth_token"
        token.parent.mkdir(parents=True)
        token.write_text("fixture-worker-token")
        home = self.smoke("anthropic", ".claude/.credentials.json", ".claude-acme/.credentials.json",
                          CLAUDE_CODE_OAUTH_TOKEN="fixture-exported-token")
        claude, spent = self.root / "bin/claude", self.root / "spent"
        claude.write_text(CLAUDE)
        result = subprocess.run([sys.executable, str(REPO / "tests/check_harness_contract.py"),
                                 "claude"], cwd=self.root, text=True, capture_output=True,
                                env={**self.env, "HOME": str(home), "SPENT": str(spent),
                                     "SMOKE_CALLER_HOME": str(self.caller),
                                     "PYTHONPATH": unboxed_worker(self.root)}, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS  3 claude:", result.stdout)
        self.assertEqual(spent.read_text().split(), ["fixture-access"] * 2)

    def test_muses_readings_are_the_listed_accounts(self):
        state = self.caller / ".agentkit/state"
        state.mkdir(parents=True)
        readings = {name: json.dumps({"fetched_at": 1, "meters": [], "error": name})
                    for name in ("usage-meta.json", "usage-meta-probe.json",
                                 "usage-meta.acme.json", "usage-meta.acme-probe.json")}
        for name, reading in readings.items():
            (state / name).write_text(reading)
        home = self.smoke("meta", ".config/muse/auth.json", ".muse-acme/muse/auth.json")
        self.assertEqual({path.name: path.read_text()
                          for path in (home / ".agentkit/state").glob("usage-meta*")},
                         {name: readings[name] for name in readings if ".acme" in name})


if __name__ == "__main__":
    unittest.main()
