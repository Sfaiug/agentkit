"""Each subscription's login says which plan it is on.

A forgotten free Google login once ran a subscription while the paid one sat unused, and
nothing on screen told the two apart (owner, 26 Oct 2026).  So each harness's `login-end`
answers `plan` beside `email` and `ends`, in the provider's own words, read where the login
keeps it: Claude's credentials, Codex's id token, and for Antigravity the tier `loadCodeAssist`
named when `usage` last asked it.  A login whose plan cannot be told answers null and the same
email and end as ever, never a failed read, and no token is printed.  The tick keeps the answer
in state/logins.json, and `logins.whose` gives the ak screen a subscription's (email, plan).
Black-box: each adapter on fake login files in a temporary HOME, the endpoint and `agy` faked;
the tick through `AK_BIN`, asking tests/fixtures/loginend.py's harness.
"""

import base64
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REPO, boxable, Home
from fixtures.loginend import Logins, kept, tick

ENDS = 1792470143
# The endpoint `usage` asks, offline: each method answers $HOME/fake/<method> and its status.
CURL = """#!/bin/sh
for a; do case "$a" in https://*:*) answer="$HOME/fake/${a##*:}";; esac; done
printf '%s\\n200' "$(cat "$answer")"
"""
TOKEN = ".gemini/antigravity-cli/antigravity-oauth-token"


def jwt(claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{body}.dummy-signature"


class Adapters(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        # macOS keeps Claude's login in the Keychain, which no HOME hides: this one finds none
        self.home.fake("security", "#!/bin/sh\nexit 1\n")

    def adapter(self, harness, verb="login-end"):
        done = self.home.run("bash", str(REPO / f"adapters/{harness}.sh"), verb)
        self.assertEqual(done.code, 0, done.err)
        self.assertNotIn("dummy", done.out + done.err)     # never a word of a token
        return json.loads(done.out)

    def claude(self, **login):
        self.home.write(".claude.json", {"oauthAccount": {"emailAddress": "owner@acme.test"}})
        self.home.write(".claude/.credentials.json", {"claudeAiOauth": {
            "accessToken": "dummy-access", "refreshToken": "dummy-refresh",
            "refreshTokenExpiresAt": ENDS * 1000, **login}})
        return self.adapter("claude")

    def test_claude_answers_its_plan_and_the_multiple_of_its_tier(self):
        self.assertEqual(self.claude(subscriptionType="max",
                                     rateLimitTier="default_claude_max_20x"),
                         {"email": "owner@acme.test", "ends": ENDS, "plan": "max 20x"})
        self.assertEqual(self.claude(subscriptionType="pro")["plan"], "pro")

    def test_codex_answers_the_chatgpt_plan_its_id_token_names(self):
        self.home.write(".codex/auth.json", {"tokens": {
            "access_token": "dummy-access", "refresh_token": "dummy-refresh",
            "id_token": jwt({"email": "owner@acme.test",
                             "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}})}})
        self.assertEqual(self.adapter("codex"),
                         {"email": "owner@acme.test", "ends": None, "plan": "plus"})

    def antigravity(self, email, tiers):
        self.home.write(TOKEN, {"token": {"access_token": "dummy-access",
                                          "refresh_token": "dummy-refresh"},
                                "id_token_email": email})
        self.home.write("fake/loadCodeAssist", {**tiers, "cloudaicompanionProject": "acme"})
        self.home.write("fake/retrieveUserQuotaSummary", {"groups": []})
        self.home.fake("agy", "#!/bin/sh\necho 1.4.7\n")

    def test_antigravity_answers_the_paid_tier_its_usage_read_named(self):
        free = {"currentTier": {"id": "free-tier", "name": "Gemini Code Assist for individuals"}}
        self.antigravity("owner@acme.test", free)
        self.home.fake("curl", CURL)
        self.adapter("antigravity", "usage")
        self.assertEqual(self.adapter("antigravity"), {
            "email": "owner@acme.test", "ends": None,
            "plan": "Gemini Code Assist for individuals"})
        self.antigravity("owner@acme.test", {**free, "paidTier": {"id": "g1-pro-tier",
                                                                  "name": "Google AI Pro"}})
        self.adapter("antigravity", "usage")
        self.assertEqual(self.adapter("antigravity")["plan"], "Google AI Pro")
        # the login `usage` read is not the one now signed in: its plan is not this one's
        self.antigravity("other@acme.test", free)
        self.assertEqual(self.adapter("antigravity"),
                         {"email": "other@acme.test", "ends": None, "plan": None})

    def test_a_login_whose_plan_is_unknown_answers_null_and_the_rest_as_before(self):
        self.assertEqual(self.claude(),
                         {"email": "owner@acme.test", "ends": ENDS, "plan": None})
        self.home.write(".codex/auth.json", {"tokens": {
            "access_token": "dummy-access", "id_token": jwt({"email": "owner@acme.test"})}})
        self.assertEqual(self.adapter("codex"),
                         {"email": "owner@acme.test", "ends": None, "plan": None})
        # the endpoint out of reach: this Home's curl refuses every call
        self.antigravity("owner@acme.test", {})
        self.adapter("antigravity", "usage")
        self.assertEqual(self.adapter("antigravity"),
                         {"email": "owner@acme.test", "ends": None, "plan": None})
        for harness in ("muse", "grokbuild"):
            self.assertEqual(self.adapter(harness), {"email": None, "ends": None, "plan": None})


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class Tick(unittest.TestCase):
    def test_the_menu_s_function_answers_email_and_plan_after_the_tick_s_read(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"beta": {"harness": "claude", "provider": "test"}},
                       providers={"test": {"mode": "subscription", "accounts": ["default", "two"]}})
        logins = Logins(home)
        logins.answer("default", "owner@acme.test", ENDS, "Google AI Pro")
        logins.answer("two", "two@acme.test", None)
        tick(home)
        self.assertEqual(kept(home)["test"]["default"]["plan"], "Google AI Pro")
        done = home.run(sys.executable, "-c", "import json; from agentkit import logins; "
                        "print(json.dumps([logins.whose('test'), logins.whose('test', 'two'), "
                        "logins.whose('acme')]))", cwd=REPO, env={"PYTHONPATH": str(REPO)})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out), [["owner@acme.test", "Google AI Pro"],
                                                ["two@acme.test", None], [None, None]])


if __name__ == "__main__":
    unittest.main()
