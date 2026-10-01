"""`ak update`'s gate makes a real turn on every harness it lets through.

Check 3 of tests/smoke.sh -- the gate `ak update` runs -- read out of the suite and driven
offline: every adapter is a fake that records its turn, every harness binary a stub that is
never run, and `ak usage` answers nothing.  No model is called.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[1]
SMOKE = (REPO / "tests/smoke.sh").read_text()


def between(start, end):
    return SMOKE[SMOKE.index(start):SMOKE.index(end, SMOKE.index(start))]


# check 3 with the helpers it calls, and `ak usage` answering nothing
CHECK = ('. "$REPO/tests/acceptance.sh"\nak() { return 1; }\n'
         + between("model_unavailable()", "reprobe()")
         + between("newrepo()", 'echo "workdir:') + between("# --- 3:", "# --- 4:") + "finish\n")
BINARIES = {"claude": "claude", "codex": "codex", "muse": "muse", "grokbuild": "grok",
            "antigravity": "agy", "opencode": "opencode"}
# the harnesses beside Claude, Codex and Muse, and the smallest turns check 3 makes on them:
# (model, harness, model id, effort)
REST = ("grokbuild", "antigravity", "opencode")
LOGGED_IN = {harness: "0 fixture: logged in" for harness in REST}
SMALLEST = re.findall(r'"(\w+) (\w+) (\S+) (\w+)"', between("# --- 3:", "# --- 4:"))
# each harness's event log for a turn that answered, and for one that said it failed
ANSWERED = {"grokbuild": '{"type":"result","subtype":"success","is_error":false,"result":"Hello"}\n',
            "opencode": '{"type":"text","part":{"type":"text","text":"Hello"}}\n',
            "antigravity": '{"event":"result","result":{"status":"SUCCESS","response":"Hello"}}\n'}
FAILED = {"grokbuild": '{"type":"result","subtype":"error_during_execution","is_error":true,'
                       '"result":"Request failed: 503 Service Unavailable"}\n',
          "opencode": ANSWERED["opencode"] + '{"type":"error","error":{"type":"provider.unknown",'
                      '"message":"503 Service Unavailable","status":503}}\n',
          "antigravity": '{"event":"result","result":{"status":"ERROR","response":"Hello"}}\n'}
# A turn for a named account is refused, as OpenCode's adapter refuses one.
ADAPTER = '''#!/bin/bash
S=$FIXTURE/${0##*/}; S=${S%.sh}
case $1 in
  auth) read -r rc line <"$S.auth"; echo "$line"; exit "$rc" ;;
  run) [ -z "${AGENTKIT_ACCOUNT:-}" ] || { echo "fixture: account $AGENTKIT_ACCOUNT refused" >&2; exit 2; }
       printf '%s\\n' "${*:2:2}" >>"$S.runs"; cat "$5" >>"$S.prompts"; mkdir -p "$6"
       read -r rc answer <"$S.turn"; printf '%b' "$answer" >"$6/final.md"
       cat "$S.said" >"$6/stderr.log" 2>/dev/null
       cat "$S.events" >"$6/events.jsonl" 2>/dev/null
       echo fixture-session >"$6/session_id"; exit "$rc" ;;
esac
exit 97
'''


class EveryHarness(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".gate-every-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home, self.fixture = self.root / "home", self.root / "fixture"
        self.bin, self.adapters = self.root / "bin", self.root / "adapters"
        for path in (self.home, self.fixture, self.bin, self.adapters):
            path.mkdir()
        # Only these tools, so a harness this host really has is never found on PATH.
        (self.bin / "python3").symlink_to(sys.executable)
        for tool in ("bash", "git", "mkdir", "cat", "grep", "head", "tail", "sed"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        for harness in BINARIES:
            (self.adapters / f"{harness}.sh").write_text(ADAPTER)
            (self.adapters / f"{harness}.sh").chmod(0o755)

    def gate(self, auth, turns=None, said=None, events=None, env=None):
        """Check 3 where `auth` names each installed harness's answer, "<exit> <line>", `said`
        what a harness wrote to its diagnostics during its turn, `events` its event log, and
        `env` what the caller's environment adds."""
        for harness, answer in auth.items():
            stub = self.bin / BINARIES[harness]
            stub.write_text('#!/bin/sh\necho "a harness binary was run: $0" >&2\nexit 97\n')
            stub.chmod(0o755)
            (self.fixture / f"{harness}.auth").write_text(answer + "\n")
            (self.fixture / f"{harness}.turn").write_text((turns or {}).get(harness, "0 Hello") + "\n")
            (self.fixture / f"{harness}.said").write_text((said or {}).get(harness, ""))
            (self.fixture / f"{harness}.events").write_text(
                (events or {}).get(harness, ANSWERED.get(harness, "")))
        for runs in self.fixture.glob("*.runs"):
            runs.unlink()
        work = tempfile.mkdtemp(prefix="work-", dir=self.root)
        env = {"HOME": str(self.home), "PATH": str(self.bin), "WORK": work,
               "REPO": str(REPO), "SMOKE_CALLER_HOME": str(self.root / "caller"),
               "AGENTKIT_ADAPTER_DIR": str(self.adapters), "FIXTURE": str(self.fixture),
               "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_DISCORD_WEBHOOK": "off",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", **(env or {})}
        result = subprocess.run([str(self.bin / "bash"), "-c", "set -uo pipefail\n" + CHECK],
                                env=env, text=True, capture_output=True, timeout=300)
        self.assertNotIn("a harness binary was run", result.stderr)
        return result

    def turns(self, harness):
        runs = self.fixture / f"{harness}.runs"
        return runs.read_text().splitlines() if runs.exists() else []

    def test_every_harness_with_a_login_makes_its_smallest_turn(self):
        result = self.gate(LOGGED_IN)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({h: len(self.turns(h)) for h in REST}, dict.fromkeys(REST, 1),
                         result.stdout)
        self.assertEqual([h for _, h, _, _ in SMALLEST], list(REST))
        for model, harness, model_id, effort in SMALLEST:
            with self.subTest(harness=harness):
                self.assertIn(f"PASS  3c {model} ({harness}): {model_id} at {effort} "
                              "answered a one-word prompt", result.stdout)
                self.assertEqual(self.turns(harness), [f"{model_id} {effort}"])
                prompt = (self.fixture / f"{harness}.prompts").read_text()
                self.assertEqual(len(prompt.split()), 1, prompt)
                # a model the harness runs, at the lowest effort it offers that model
                catalog = tomllib.loads((REPO / f"adapters/{harness}.toml").read_text())["catalog"]
                self.assertEqual(catalog[model_id]["efforts"][0], effort)
        for model, harness in (("opus", "claude"), ("astra", "codex"), ("spark", "muse")):
            self.assertIn(f"NOT CHECKED  3a/3b {model} ({harness}): {harness} is not installed",
                          result.stdout)
        self.assertIn("3 passed, 0 failed, 0 skipped", result.stdout)

    def test_a_turn_that_fails_fails_the_gate(self):
        # an error with an answer, a success with none or only a blank line, and neither
        for harness in REST:
            for turn in ("1 Hello", "0 ", "0 \\n", "1 "):
                with self.subTest(harness=harness, turn=turn):
                    result = self.gate(LOGGED_IN, {harness: turn})
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertRegex(result.stdout, rf"FAIL  3c \w+ \({harness}\): .* gave no answer")
                    self.assertIn("2 passed, 1 failed, 0 skipped", result.stdout)

    def test_a_turn_that_says_it_is_logged_out_fails_the_gate(self):
        # An answer and exit 0 beside the harness's own logout words, as a worker's turn is
        # judged: that turn never reached the model.
        for harness in REST:
            for words in tomllib.loads((REPO / f"adapters/{harness}.toml").read_text())["auth"]["signatures"]:
                with self.subTest(harness=harness, said=words):
                    result = self.gate(LOGGED_IN, said={harness: f"error: {words}\n"})
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertRegex(result.stdout, rf"FAIL  3c \w+ \({harness}\): .* gave no "
                                     rf"answer: {re.escape(words)}")
                    self.assertIn("2 passed, 1 failed, 0 skipped", result.stdout)

    def test_a_turn_whose_events_say_it_failed_fails_the_gate(self):
        # Exit 0 and an answer, beside a record in its event log saying the turn failed.
        for harness in REST:
            with self.subTest(harness=harness):
                result = self.gate(LOGGED_IN, events={harness: FAILED[harness]})
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertRegex(result.stdout, rf"FAIL  3c \w+ \({harness}\): .* gave no "
                                 r"answer: \{.*(ERROR|error)")
                self.assertIn("2 passed, 1 failed, 0 skipped", result.stdout)

    def test_a_named_account_in_the_callers_environment_never_reaches_a_turn(self):
        # The turn runs on the login worker.auth_ok asked about, which no named account turns.
        result = self.gate(LOGGED_IN, env={"AGENTKIT_ACCOUNT": "acme"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("3 passed, 0 failed, 0 skipped", result.stdout)

    def test_a_harness_with_no_login_is_not_checked_never_passed(self):
        token = self.home / ".gemini/antigravity-cli/antigravity-oauth-token"
        # OpenCode's settings with no key in them are no login, not a broken one.
        settings = self.home / ".config/opencode/opencode.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"theme": "dark"}')
        creds = self.home / ".claude/.credentials.json"
        result = self.gate({
            "grokbuild": "0 fixture: logged in",
            "antigravity": f"1 agy: no {token}; run `agy` and sign in",
            "opencode": f"1 opencode: no provider key in {settings} and none saved; "
                        "run `opencode auth login`",
            "claude": f"1 claude: no OAuth credentials in {creds} and no "
                      "CLAUDE_CODE_OAUTH_TOKEN; run `claude login`"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS  3c grok (grokbuild)", result.stdout)
        for line in (f"3c gemini (antigravity): agy: no {token}",
                     f"3c mimo (opencode): opencode: no provider key in {settings}",
                     f"3a/3b opus (claude): claude: no OAuth credentials in {creds}",
                     "3a/3b astra (codex): codex is not installed",
                     "3a/3b spark (muse): muse is not installed"):
            self.assertIn("NOT CHECKED  " + line, result.stdout)
        self.assertEqual(self.turns("antigravity") + self.turns("opencode"), [])
        # neither a pass nor a skip counted as one
        self.assertNotIn("SKIP ", result.stdout)
        self.assertIn("1 passed, 0 failed, 0 skipped", result.stdout)
        self.assertNotIn("counted as passed", result.stdout)

    def test_a_broken_opencode_settings_file_still_fails(self):
        # Settings that parse and hold no key are no login; a file that is empty or no longer
        # parses may have held one, and one holding a key the adapter would not take (not a
        # string, or blank) holds a broken one: each fails as every broken saved login does.
        settings = self.home / ".config/opencode/opencode.json"
        settings.parent.mkdir(parents=True)
        for text in ('{"provider": {"mimo": {"apiKey": "k', "",
                     '{"provider": {"mimo": {"apiKey": 123}}}',
                     '{"provider": {"mimo": {"options": {"apiKey": ""}}}}'):
            with self.subTest(settings=text):
                settings.write_text(text)
                result = self.gate({**LOGGED_IN, "opencode": f"1 opencode: no provider key in "
                                    f"{settings} and none saved; run `opencode auth login`"})
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("FAIL  3c: required model mimo login check failed", result.stdout)
                self.assertNotIn("NOT CHECKED  3c mimo", result.stdout)
                self.assertEqual(self.turns("opencode"), [])


if __name__ == "__main__":
    unittest.main()
