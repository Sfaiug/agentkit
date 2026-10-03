"""`ak update`'s gate makes a real turn on every harness it lets through.

Check 3 of tests/smoke.sh -- the gate `ak update` runs -- read out of the suite and driven
offline: every adapter is a fake that records its turn, every harness binary a stub that is
never run, and `ak usage` answers nothing.  No model is called.
"""

import os
from pathlib import Path
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
         + between("newrepo()", 'echo "workdir:') + between("# --- 3:", "# --- 3a:") + "finish\n")
MANIFESTS = {p.stem: tomllib.loads(p.read_text()) for p in (REPO / "adapters").glob("*.toml")}
BINARIES = {h: m["update"]["version"][0] for h, m in MANIFESTS.items()}
LOGGED_IN = {h: "0 fixture: logged in" for h in MANIFESTS}
WORD = "DONE"


def unboxed_worker(root):
    # These adapters are fixtures; test_worker_box exercises the real namespaces.
    (root / "sitecustomize.py").write_text(f'''from contextlib import nullcontext
import sys
sys.path.insert(0, {str(REPO)!r})
from agentkit import box
def command(argv, env, *_args, **_kw):
    return nullcontext((argv, env, {{}}))
box.command = command
''')
    return str(root)


def text(part):
    """One text part of an OpenCode message, as its event log streams it."""
    return '{"type":"text","part":{"type":"text","messageID":"msg_1","text":"%s"}}\n' % part


# A turn for a named account is refused, as OpenCode's adapter refuses one.
ADAPTER = '''#!/bin/bash
S=$FIXTURE/${0##*/}; S=${S%.sh}
case $1 in
  auth) read -r rc line <"$S.auth"; echo "$line"; exit "$rc" ;;
  run) [ -z "${AGENTKIT_ACCOUNT:-}" ] || { echo "fixture: account $AGENTKIT_ACCOUNT refused" >&2; exit 2; }
       printf '%s\\n' "${*:2:2}" >>"$S.runs"; cat "$5" >>"$S.prompts"; mkdir -p "$6"
       read -r rc answer <"$S.turn"
       cat "$S.said" >"$6/stderr.log" 2>/dev/null
       cat "$S.events" >"$6/events.jsonl" 2>/dev/null
       if [ -n "${7:-}" ]; then
         printf '%s\\n' "${7#fixture:}" >"$6/final.md"
         printf '%s\\n' "$7" >"$6/session_id"
       else
         printf '%b' "$answer" >"$6/final.md"
         sed -n 's/^Run: //p' "$5" >"$6/commands.sh"
         if [ "$rc" = 0 ] && ! grep -q '"type":"error"' "$6/events.jsonl"; then
           (cd "$4" && bash "$6/commands.sh") || exit $?
         fi
         filename=$(sed -n 's/.* > //p' "$6/commands.sh")
         printf 'fixture:%s\\n' "$filename" >"$6/session_id"
       fi
       exit "$rc" ;;
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
            shutil.copy2(REPO / "adapters" / f"{harness}.toml", self.adapters)
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
            (self.fixture / f"{harness}.turn").write_text((turns or {}).get(harness, f"0 {WORD}") + "\n")
            (self.fixture / f"{harness}.said").write_text((said or {}).get(harness, ""))
            (self.fixture / f"{harness}.events").write_text((events or {}).get(harness, ""))
        for runs in self.fixture.glob("*.runs"):
            runs.unlink()
        work = tempfile.mkdtemp(prefix="work-", dir=self.root)
        env = {"HOME": str(self.home), "PATH": str(self.bin), "WORK": work,
               "PYTHONPATH": unboxed_worker(self.root),
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

    def test_every_harness_with_a_login_makes_the_same_two_turns(self):
        result = self.gate(LOGGED_IN)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for harness, manifest in MANIFESTS.items():
            with self.subTest(harness=harness):
                model, effort = (manifest["check"][k] for k in ("model", "effort"))
                self.assertIn(model, manifest["catalog"])
                self.assertEqual(effort, manifest["catalog"][model]["efforts"][0])
                self.assertIn(f"PASS  3 {harness}: wrote the file, handed in done", result.stdout)
                self.assertEqual(self.turns(harness), [f"{model} {effort}"] * 2)
                prompt = (self.fixture / f"{harness}.prompts").read_text()
                self.assertIn("hand-in done", prompt)
                self.assertIn("What file did you just create?", prompt)
                self.assertNotIn("You are the executor", prompt)
        self.assertIn(f"{len(MANIFESTS)} passed, 0 failed, 0 skipped", result.stdout)

    def test_a_failed_or_empty_turn_fails_the_gate(self):
        for harness in MANIFESTS:
            for turn in (f"1 {WORD}", "0 ", "0 \\n", "1 "):
                with self.subTest(harness=harness, turn=turn):
                    result = self.gate(LOGGED_IN, {harness: turn})
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(f"FAIL  3 {harness}:", result.stdout)

    def test_an_opencode_turn_cut_short_fails_the_gate(self):
        # OpenCode exits 0 on a turn its provider ended: no text or partial text, an error
        # record in its event log, and the adapter's copy of that error in stderr.log.
        error = '{"type":"error","error":{"message":"503 Service Unavailable","status":503}}\n'
        for partial in ("", "Sure"):
            with self.subTest(partial=partial):
                result = self.gate(LOGGED_IN, {"opencode": f"0 {partial}"},
                                   said={"opencode": "503 Service Unavailable\n"},
                                   events={"opencode": (text(partial) if partial else "") + error})
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("FAIL  3 opencode:", result.stdout)
                self.assertIn(f"{len(MANIFESTS) - 1} passed, 1 failed, 0 skipped", result.stdout)

    def test_an_opencode_answer_in_parts_after_a_warning_passes_the_gate(self):
        # A stream error the turn recovered from, then one message in two text parts, which
        # the adapter joins into final.md, then a step that finished.
        events = ('{"type":"stream_error","error":{"message":"429 Too Many Requests; retrying"}}\n'
                  + text(WORD) + text("How can I help?")
                  + '{"type":"step_finish","part":{"type":"step-finish","messageID":"msg_1",'
                    '"reason":"stop"}}\n')
        result = self.gate(LOGGED_IN, {"opencode": f"0 {WORD}\\nHow can I help?\\n"},
                           events={"opencode": events})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS  3 opencode:",
                      result.stdout)
        self.assertIn(f"{len(MANIFESTS)} passed, 0 failed, 0 skipped", result.stdout)

    def test_a_named_account_in_the_callers_environment_never_reaches_a_turn(self):
        # The turn runs on the login worker.auth_ok asked about, which no named account turns.
        result = self.gate(LOGGED_IN, env={"AGENTKIT_ACCOUNT": "acme"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"{len(MANIFESTS)} passed, 0 failed, 0 skipped", result.stdout)

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
        self.assertIn("PASS  3 grokbuild:", result.stdout)
        for line in (f"3 antigravity: agy: no {token}",
                     f"3 opencode: opencode: no provider key in {settings}",
                     f"3 claude: claude: no OAuth credentials in {creds}",
                     "3 codex: codex is not installed",
                     "3 muse: muse is not installed"):
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
                self.assertIn("FAIL  3 opencode:", result.stdout)
                self.assertNotIn("NOT CHECKED  3 opencode:", result.stdout)
                self.assertEqual(self.turns("opencode"), [])


if __name__ == "__main__":
    unittest.main()
