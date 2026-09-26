"""A provider with several subscriptions runs a worker turn on the account with room.

Each account of `[providers.anthropic] accounts` is its own login: the real adapters/claude.sh
reads the account's worker token by the name ak hands it in AGENTKIT_ACCOUNT, and its meters
with it.  A fake `claude` and a fake `curl` on PATH answer per token, a fake second provider
answers beside it, and HOME is temporary, so no real login, provider or endpoint is reached.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, usage  # noqa: E402

# The bearer token out of the `-H @file` header, and the answer from `resp-<token>`: the
# code on the first line, the body on the rest.
FAKE_CURL = """#!/usr/bin/env bash
hf=""; prev=""
for a in "$@"; do
  if [ "$prev" = "-H" ]; then case "$a" in @*) hf=${a#@};; esac; fi
  prev=$a
done
tok=$(sed -n 's/^Authorization: Bearer //p' "$hf" 2>/dev/null | head -1)
resp="$FAKE/resp-$tok"
[ -f "$resp" ] || { printf '\\n000\\n'; exit 0; }
printf '%s\\n%s\\n' "$(sed -n '2,$p' "$resp")" "$(sed -n '1p' "$resp")"
"""

# One JSON line per turn: the login it ran on and the conversation it resumed.  A token with a
# `refuse-<token>` file is refused as a spent subscription is, in Claude's own words; one with a
# `dry-<token>` file fails with an answer that names its quota, which only `worker_dry` reads.
FAKE_CLAUDE = """#!/usr/bin/env bash
sid=""
while [ $# -gt 0 ]; do [ "$1" = --resume ] && sid=$2; shift; done
cat >/dev/null
jq -nc --arg resume "$sid" '{token: $ENV.CLAUDE_CODE_OAUTH_TOKEN, config: $ENV.CLAUDE_CONFIG_DIR,
    account: $ENV.AGENTKIT_ACCOUNT, resume: $resume}' >>"$FAKE/claude-calls"
sid=${sid:-s1}
if [ -f "$FAKE/refuse-${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  printf '{"type":"result","is_error":true,"result":"Claude AI usage limit reached","session_id":"%s"}\\n' "$sid"
  exit 1
fi
if [ -f "$FAKE/dry-${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  printf '{"type":"result","result":"## Summary\\\\nStopped on insufficient_quota.","session_id":"%s"}\\n' "$sid"
  exit 1
fi
printf '{"type":"result","result":"## Summary\\\\nDone on %s.","session_id":"%s"}\\n' \\
    "${CLAUDE_CODE_OAUTH_TOKEN:-}" "$sid"
"""

# Another company with more room than either account: where a handover would go.
FAKE_OTHER = """#!/usr/bin/env bash
case "${1:-}" in
usage) printf '{"provider":"other","error":null,"meters":[{"name":"weekly","used":0,
  "resets_at":%s,"window_secs":604800}]}\\n' "$(( $(date +%s) + 86400 ))" ;;
auth) echo "other: fake login" ;;
run) touch "$FAKE/other-ran"; exit 1 ;;
*) exit 2 ;;
esac
"""

CONFIG = """[defaults]
orchestrator = "opus"
workers = ["opus", "spare"]

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "high"
provider = "anthropic"

[models.spare]
harness = "other"
model = "spare-1"
effort = "high"
provider = "other"

[providers.anthropic]
{accounts}
[providers.other]
"""


def script(path, text):
    path.write_text(text)
    path.chmod(0o755)


class Accounts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-accounts-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        self.fake, bin, adapters = root / "fake", root / "bin", root / "adapters"
        for d in (self.fake, bin, adapters):
            d.mkdir()
        script(bin / "curl", FAKE_CURL)
        script(bin / "claude", FAKE_CLAUDE)
        script(adapters / "other.sh", FAKE_OTHER)
        (adapters / "claude.sh").symlink_to(REPO / "adapters/claude.sh")
        home = root / ".agentkit"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, key, home / key.lower()))
        self.stack.enter_context(patch.object(config, "HOME", home))
        self.stack.enter_context(patch.object(config, "CODE", root / "code"))
        env = {k: v for k, v in os.environ.items()
               if k not in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR",
                            "AGENTKIT_RUN_DIR", "AGENTKIT_SESSION", "AGENTKIT_ACCOUNT",
                            "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR")}
        env.update(HOME=str(root), PATH=f"{bin}{os.pathsep}{env.get('PATH', '')}",
                   FAKE=str(self.fake), AGENTKIT_ADAPTER_DIR=str(adapters),
                   AK_RUN_DEPTH="0", AK_MAX_RUNS="0", AGENTKIT_DISCORD_WEBHOOK="off")
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        (config.SECRETS / "claude_oauth_token").write_text("tok-default")
        (config.SECRETS / "claude_oauth_token.second").write_text("tok-second")
        self.work = root / "work"
        self.work.mkdir()
        self.lines = []

    # --- the fixture ------------------------------------------------------

    def configure(self, accounts='accounts = ["default", "second"]\n'):
        (config.HOME / "config.toml").write_text(CONFIG.format(accounts=accounts))
        self.cfg = config.load()

    def meters(self, token, weekly, session=0):
        """What the usage endpoint answers that token: a week and a session this far spent."""
        def at(offset):
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))
        body = {"limits": [
            {"kind": "weekly_all", "group": "weekly", "percent": weekly, "resets_at": at(3 * 86400)},
            {"kind": "session", "group": "session", "percent": session, "resets_at": at(3600)}]}
        (self.fake / f"resp-{token}").write_text(f"200\n{json.dumps(body)}\n")

    def turn(self):
        out = self.root / "run" / "round-1" / "executor"
        out.parent.mkdir(parents=True, exist_ok=True)
        return run.call_retrying(self.cfg, "opus", "Do the task.", self.work, out, "executor",
                                 None, self.lines.append, limit=120)

    def calls(self):
        try:
            text = (self.fake / "claude-calls").read_text()
        except OSError:
            return []
        return [json.loads(line) for line in text.splitlines()]

    # --- the accounts -----------------------------------------------------

    def test_the_first_account_at_100_percent_runs_the_turn_on_the_second(self):
        self.meters("tok-default", 100)
        self.meters("tok-second", 20)
        # a reading taken before the accounts were listed is read again, not trusted for minutes
        self.configure(accounts="")
        self.assertNotIn("accounts", usage.collect(self.cfg)["anthropic"])
        self.configure()
        providers = usage.collect(self.cfg)
        anthropic = providers["anthropic"]
        self.assertTrue(anthropic["accounts"]["default"]["exhausted"])
        self.assertFalse(anthropic["accounts"]["second"]["exhausted"])
        # the provider is the account a turn runs on next, so the model is still eligible
        self.assertEqual(anthropic["account"], "second")
        self.assertFalse(usage.model_exhausted(self.cfg, "opus", providers)[0])
        # `ak usage`: each account's meters on a line of its own
        rows = {row[0]: row for row in usage.rows(self.cfg, providers)}
        self.assertEqual(rows["anthropic:default"][2], "0%")
        self.assertEqual(rows["anthropic:second"][2], "80%")
        self.assertNotIn("anthropic", rows)
        text = usage.render(self.cfg, providers, ["opus"])
        self.assertIn("anthropic:default", text)
        self.assertIn("anthropic:second", text)

        code, answer, session, _ = self.turn()
        self.assertEqual((code, session), (0, "s1"))
        self.assertIn("Done on tok-second", answer)
        [call] = self.calls()
        self.assertEqual(call["token"], "tok-second")
        self.assertEqual(call["account"], "second")
        self.assertEqual(call["config"], str(self.root / ".claude-second"))
        # its conversations are the usual ones, so the next account can resume them
        self.assertEqual((self.root / ".claude-second/projects").resolve(),
                         (self.root / ".claude/projects").resolve())

    def test_a_quota_refusal_on_the_first_account_hands_the_turn_to_the_second(self):
        self.configure()
        self.meters("tok-default", 10)
        self.meters("tok-second", 30)
        (self.fake / "refuse-tok-default").touch()
        self.assertEqual(usage.account(self.cfg, "anthropic"), ("default", True))

        # no RanDry, which is what hands the work to another company's model
        code, answer, session, dead = self.turn()
        self.assertEqual((code, session, dead), (0, "s1", False))
        self.assertIn("Done on tok-second", answer)
        self.assertEqual([(c["token"], c["resume"]) for c in self.calls()],
                         [("tok-default", ""), ("tok-second", "s1")])
        self.assertFalse((self.fake / "other-ran").exists())
        self.assertTrue(any("going on with account second" in line for line in self.lines),
                        self.lines)
        # the refusal parks that account alone: the provider still runs on the other
        providers = usage.collect(self.cfg)
        self.assertTrue(providers["anthropic"]["accounts"]["default"]["exhausted"])
        self.assertIn("exhausted_until", providers["anthropic"]["accounts"]["default"])
        self.assertEqual(usage.account(self.cfg, "anthropic"), ("second", True))
        self.assertFalse(usage.model_exhausted(self.cfg, "opus", providers)[0])

        # ... and once the second is refused too, the turn goes to another model
        (self.fake / "refuse-tok-second").touch()
        with self.assertRaises(run.RanDry):
            self.turn()
        self.assertEqual(self.calls()[-1]["token"], "tok-second")
        self.assertEqual(usage.account(self.cfg, "anthropic")[1], False)
        self.assertTrue(usage.model_exhausted(self.cfg, "opus", usage.collect(self.cfg))[0])

    def test_quota_only_a_failed_answer_names_goes_to_the_next_account_too(self):
        self.configure()
        self.meters("tok-default", 10)
        self.meters("tok-second", 30)
        (self.fake / "dry-tok-default").touch()
        code, answer, session, _ = self.turn()
        self.assertEqual((code, session), (0, "s1"))
        self.assertIn("Done on tok-second", answer)
        self.assertEqual([(c["token"], c["resume"]) for c in self.calls()],
                         [("tok-default", ""), ("tok-second", "s1")])
        self.assertTrue(any("ran dry on account default: ran dry on 'insufficient_quota'" in line
                            for line in self.lines), self.lines)
        self.assertEqual(usage.account(self.cfg, "anthropic"), ("second", True))
        self.assertTrue(usage.collect(self.cfg)["anthropic"]["accounts"]["default"]["exhausted"])

    def test_a_provider_without_accounts_is_one_login_as_before(self):
        self.configure(accounts="")
        self.meters("tok-default", 10)
        self.meters("tok-second", 0)
        self.assertEqual(usage.account(self.cfg, "anthropic"), (None, None))
        providers = usage.collect(self.cfg)
        self.assertNotIn("accounts", providers["anthropic"])
        self.assertNotIn("account", providers["anthropic"])
        self.assertEqual(providers["anthropic"]["meters"][0]["used"], 10)
        self.assertTrue((config.STATE / "anthropic-probe.lock").exists())
        self.assertEqual(sorted(config.STATE.glob("anthropic.*")), [])
        self.assertEqual([row[0] for row in usage.rows(self.cfg, providers)],
                         ["anthropic", "other"])

        code, answer, _, _ = self.turn()
        self.assertEqual(code, 0)
        self.assertIn("Done on tok-default", answer)
        [call] = self.calls()
        self.assertEqual((call["token"], call["config"], call["account"]),
                         ("tok-default", None, None))
        self.assertFalse((self.root / ".claude-second").exists())

        # a quota refusal parks the provider and hands the work over, as it always did
        (self.fake / "refuse-tok-default").touch()
        with self.assertRaises(run.RanDry):
            self.turn()
        providers = usage.collect(self.cfg)
        self.assertIn("exhausted_until", providers["anthropic"])
        self.assertTrue(usage.model_exhausted(self.cfg, "opus", providers)[0])
        self.assertEqual([c["token"] for c in self.calls()], ["tok-default", "tok-default"])


if __name__ == "__main__":
    unittest.main()
