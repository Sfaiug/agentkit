"""The Claude adapter says the usage-limit resets a login holds, by kind, and spends one of a kind.

The owner (10 Nov 2026): "I also want this to be the case for Claude subscriptions, and also I want
it to be able to use a reset the same way its possible for chatgpt."  `adapters/claude.sh usage`
asks for them as Claude Code 2.1.322 does, on its one usage request, and counts them the way
Claude Code sorts them; `reset KIND` claims that kind's first usable grant once.  The real adapter,
a fake `curl` serving Anthropic's answers of 10 and 11 Nov 2026 and writing down every request, a
fake `claude --version`, a temporary HOME and an invented login: nothing reaches Anthropic.
"""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

REPO = Path(__file__).resolve().parents[1]
TOKEN = "sk-ant-oat01-invented-acme"
ORG = "0f0e0d0c-0b0a-4908-8706-050403020100"
AGENT = "User-Agent: claude-cli/2.1.322 (external, cli)"
USAGE = "https://api.anthropic.com/api/oauth/usage?cedar_ember=1"
SPEND = f"https://api.anthropic.com/api/organizations/{ORG}/reset_rate_limits"

LIMITS = [{"kind": "session", "group": "session", "percent": 12,
           "resets_at": "2026-11-11T15:00:00.120000+00:00", "scope": None},
          {"kind": "weekly_all", "group": "weekly", "percent": 100,
           "resets_at": "2026-11-13T11:59:59.674206+00:00", "scope": None},
          {"kind": "weekly_scoped", "group": "weekly", "percent": 8,
           "resets_at": "2026-11-13T11:59:59.674345+00:00",
           "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}}]
METERS = ["session", "weekly_all", "weekly_scoped"]
GRANT = {"resets_total": 1, "resets_left": 1, "ends_at": "2027-03-09T07:59:00+00:00",
         "clears": ["seven_day_overage_included"], "paused": False, "usable_now": True,
         "use_requires_limit": False, "type": "full", "gives_back_weekly": True}
BLOCK = {"eligible": True, "ineligible_reason": None, "at_limit": True, "exhausted": ["seven_day"],
         "grants": [{**GRANT, "id": "month-reset", "ends_at": "2026-12-10T22:00:00+00:00",
                     "clears": ["seven_day", "seven_day_overage_included"], "type": "weekly",
                     "gives_back_weekly": False},
                    {**GRANT, "id": "launch-fable"},
                    {**GRANT, "id": "launch-fable-6mo"}],
         "next_grant_id": "month-reset", "weekly_resets_at": "2026-11-13T12:00:00+00:00",
         "cooldown_until": None}
HELD = [{"kind": "weekly", "left": 1, "usable": True}, {"kind": "Fable", "left": 2, "usable": True}]

# Each request, as Anthropic would see it, a line of `asked`: its method, URL, headers (a header
# file's lines among them), JSON body and the argument list it ran with.  The answer is the next
# of `usage.json` or `reset.json`, [code, body], the last one again once they run out; a null
# body is an answer cut off after its headers.
FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, sys
args, fake = sys.argv[1:], os.environ["FAKE"]
request = {"method": "GET", "headers": [], "argv": args}
for flag, value in zip(args, args[1:]):
    if flag == "-H":
        request["headers"] += open(value[1:]).read().splitlines() if value[:1] == "@" else [value]
    elif flag == "-X":
        request["method"] = value
    elif flag == "-d":
        request["data"] = json.loads(value)
request["url"] = next(a for a in args if a.startswith("https://"))
verb = "reset" if request["method"] == "POST" else "usage"
log = os.path.join(fake, "asked")
before = [json.loads(line) for line in open(log)] if os.path.exists(log) else []
with open(log, "a") as out:
    out.write(json.dumps(request) + "\n")
answers = json.load(open(os.path.join(fake, verb + ".json")))
code, body = answers[min(sum(each["method"] == request["method"] for each in before),
                         len(answers) - 1)]
sys.stdout.write(("" if body is None else json.dumps(body)) + "\n" + str(code))
sys.exit(28 if body is None else 0)
'''


def answer(block=BLOCK, **grants):
    """The usage endpoint's body holding that block, each named grant with those fields."""
    block = copy.deepcopy(block)
    for grant in (block or {}).get("grants", []):
        grant.update(grants.get(grant["id"].replace("-", "_"), {}))
    return {"limits": LIMITS, **({"cedar_ember": block} if block is not None else {})}


class Resets(unittest.TestCase):
    def adapter(self, *argv, usage=(answer(),), spend=()):
        """What `claude.sh <argv>` prints, the usage endpoint answering `usage` in turn and the
        spend `spend`, and every request it made."""
        with tempfile.TemporaryDirectory(prefix="ak-test-claude-resets-") as tmp:
            root = Path(tmp)
            fake, bin = root / "fake", root / "bin"
            for folder in (fake, bin, root / ".agentkit/secrets"):
                folder.mkdir(parents=True)
            (root / ".agentkit/secrets/claude_oauth_token").write_text(TOKEN)
            (root / ".claude.json").write_text(json.dumps(
                {"oauthAccount": {"organizationUuid": ORG}}))
            (fake / "usage.json").write_text(json.dumps([[200, body] for body in usage]
                                                        if isinstance(usage, tuple) else usage))
            (fake / "reset.json").write_text(json.dumps([list(each) for each in spend]))
            for name, script in (("curl", FAKE_CURL),
                                 ("claude", "#!/bin/sh\n[ \"$1\" = --version ] || exit 1\n"
                                            "echo '2.1.322 (Claude Code)'\n"),
                                 ("security", "#!/bin/sh\nexit 1\n")):   # no Keychain login
                (bin / name).write_text(script)
                (bin / name).chmod(0o755)
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("AK_", "AGENTKIT_"))
                   and k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN")}
            env.update(HOME=tmp, PATH=f"{bin}{os.pathsep}{os.environ['PATH']}", FAKE=str(fake))
            proc = subprocess.run(["bash", str(REPO / "adapters/claude.sh"), *argv], env=env,
                                  capture_output=True, text=True, timeout=60)
            log = fake / "asked"
            asked = ([json.loads(line) for line in log.read_text().splitlines()]
                     if log.exists() else [])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(TOKEN, proc.stdout + proc.stderr)
        for request in asked:
            self.assertNotIn(TOKEN, json.dumps(request["argv"]))
            self.assertIn(f"Authorization: Bearer {TOKEN}", request["headers"])
            self.assertIn(AGENT, request["headers"])
        return json.loads(proc.stdout), asked

    def posted(self, asked):
        return [request for request in asked if request["method"] == "POST"]

    def test_usage_asks_once_and_counts_the_resets_by_kind_beside_its_meters(self):
        said, asked = self.adapter("usage")
        self.assertEqual([request["url"] for request in asked], [USAGE])
        self.assertEqual((said["resets"], said["reset_kinds"]), (3, HELD))
        self.assertEqual([meter["name"] for meter in said["meters"]], METERS)
        self.assertIsNone(said["error"])

    def test_a_kind_none_of_whose_grants_can_be_spent_now_is_not_usable(self):
        said, _ = self.adapter("usage", usage=(answer(launch_fable={"usable_now": False},
                                                      launch_fable_6mo={"usable_now": False}),))
        self.assertEqual(said["reset_kinds"],
                         [HELD[0], {"kind": "Fable", "left": 2, "usable": False}])

    def test_an_ineligible_login_a_paused_block_or_no_block_holds_none(self):
        paused = {"paused": True}
        for case, body in (("ineligible", answer({**BLOCK, "eligible": False,
                                                  "ineligible_reason": "surface"})),
                           ("paused", answer(month_reset=paused, launch_fable=paused,
                                             launch_fable_6mo=paused)),
                           ("no block", answer(None))):
            with self.subTest(case):
                said, asked = self.adapter("usage", usage=(body,))
                self.assertEqual(len(asked), 1)
                self.assertEqual((said["resets"], said["reset_kinds"]), (0, []))
                self.assertEqual([meter["name"] for meter in said["meters"]], METERS)

    def test_a_spend_claims_the_kind_s_first_usable_grant_once_and_says_what_is_left(self):
        spent = {"result": "reset", "reason": None, "resets_left": 0,
                 "cleared": ["seven_day_overage_included"],
                 "weekly_resets_at": "2026-11-13T12:00:00+00:00", "cooldown_until": None}
        after = answer(launch_fable={"resets_left": 0, "usable_now": False})
        ids = []
        for case, usage, told in (
                ("read after", (answer(), after),
                 {"code": "reset", "available": 2,
                  "reset_kinds": [HELD[0], {"kind": "Fable", "left": 1, "usable": True}],
                  "meters": METERS}),
                ("no read after", [[200, answer()], [503, {"error": "overloaded"}]],
                 {"code": "reset", "available": 2}),
                ("a read after cut off", [[200, answer()], [200, None]],
                 {"code": "reset", "available": 2})):
            with self.subTest(case):
                said, asked = self.adapter("reset", "Fable", usage=usage, spend=[(200, spent)])
                [post] = self.posted(asked)
                self.assertEqual(post["url"], SPEND)
                data = post["data"]
                ids.append(str(uuid.UUID(data.pop("request_id"))))
                self.assertEqual(data, {"program": "cedar_ember", "grant_id": "launch-fable"})
                self.assertEqual([request["url"] for request in asked], [USAGE, SPEND, USAGE])
                if "meters" in said:
                    said["meters"] = [meter["name"] for meter in said["meters"]]
                self.assertEqual(said, told)
        self.assertEqual(len(set(ids)), len(ids), ids)

    def test_a_spend_refused_says_the_endpoint_s_result(self):
        refused = {"result": "cooldown", "reason": "too soon", "resets_left": 1, "cleared": [],
                   "weekly_resets_at": None, "cooldown_until": "2026-11-12T10:00:00+00:00"}
        said, asked = self.adapter("reset", "weekly", spend=[(200, refused)])
        self.assertEqual([post["data"]["grant_id"] for post in self.posted(asked)], ["month-reset"])
        self.assertEqual(said, {"code": "cooldown", "reason": "too soon"})

    def test_no_usable_grant_of_the_kind_or_no_kind_posts_nothing(self):
        # no kind is unavailable before the status is read, so even a status that fails says so
        for argv, usage in ((("reset", "5-hour"), (answer(),)),
                            (("reset",), [[503, {"error": "overloaded"}]])):
            with self.subTest(argv=argv):
                said, asked = self.adapter(*argv, usage=usage)
                self.assertEqual(self.posted(asked), [])
                self.assertEqual(said, {"code": "unavailable"})


if __name__ == "__main__":
    unittest.main()
