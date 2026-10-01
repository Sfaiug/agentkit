"""Smoke's real calls judge the usual login, even when another subscription has room.

Check 3 is extracted from smoke.sh and run with fake workers and adapters in a temporary
HOME. Neither the caller's state nor a real provider is touched.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SMOKE = (REPO / "tests/smoke.sh").read_text()
CHECK_3 = SMOKE[SMOKE.index("# --- 3:"):SMOKE.index("# --- 4:")]
DEPENDENTS = ('\nif skip_spent 4/4b/4c/4d/31d opus; then :; else echo ATTEMPT_OPUS; fi\n'
              'if skip_spent 31e astra; then :; else echo ATTEMPT_ASTRA; fi\nfinish\n')
HARNESSES = (("anthropic", "opus", "3a/3b"), ("openai", "astra", "3a/3b"),
             ("meta", "spark", "3a/3b"), ("xai", "grok", "3c"),
             ("google", "gemini", "3c"), ("mimo", "mimo", "3c"))
DEPENDENT_LABELS = {"opus": ("4", "4b", "4c", "4d", "31d"), "astra": ("31e",)}
FAKES = r'''
python3() {
  case "$*" in
    *check_claude_stream.py*) shift 2; "$@" ;;
    *) "$PYTHON_BIN" "$@" ;;
  esac
}
model_unavailable() { return 0; }
skip_unavailable() { return 1; }
newrepo() { local d="$WORK/$1"; mkdir -p "$d"; printf '%s' "$d"; }
ak() {
  case "$1" in
    usage) cat "$WORK/sandbox.json" ;;
    worker)
      local model=$2 out='' workspace='' resumed=0
      shift 3
      while [ $# != 0 ]; do
        case "$1" in
          --out) out=$2 ;;
          --workspace) workspace=$2 ;;
          --session) resumed=1 ;;
          *) return 97 ;;
        esac
        shift 2
      done
      echo "$model" >>"$WORK/calls"
      mkdir -p "$out"
      if [ "$model" = "${REFUSED_MODEL:-}" ]; then
        echo 'Claude AI usage limit reached' >"$out/final.md"
        return 1
      fi
      echo fixture-session >"$out/session_id"
      if [ "$resumed" = 0 ]; then
        echo hello >"$workspace/hello.txt"; echo DONE >"$out/final.md"
        "$PYTHON_BIN" "$REPO/tests/fixtures/hand_in.py" smoke "$out" "$workspace" || return $?
      else
        echo hello.txt >"$out/final.md"
      fi ;;
    *) return 97 ;;
  esac
}
'''
ADAPTER = '''#!/bin/bash
[ "$1" = run ] || exit 97
echo "${0##*/}" >>"$WORK/calls"
mkdir -p "$6"
echo PONG >"$6/final.md"
'''


class BorrowedLogin(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-borrowed-login-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.host = self.root / "caller/.agentkit/state/usage.json"
        self.host.parent.mkdir(parents=True)
        self.adapters = self.root / "adapters"
        self.adapters.mkdir()
        for harness in ("grokbuild", "antigravity", "opencode"):
            adapter = self.adapters / f"{harness}.sh"
            adapter.write_text(ADAPTER)
            adapter.chmod(0o755)
        self.reset = int(time.time()) + 86400
        self.when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(self.reset))

    def record(self, used, reset=None):
        return {"meters": [{"name": "weekly_all", "used": used,
                            "exhausted": used >= 100, "window_secs": 604800,
                            "resets_at": self.reset if reset is None else reset}]}

    def accounts(self, usual, other):
        return {**other, "account": "second", "accounts": {"default": usual, "second": other}}

    def gate(self, sandbox, host=None, **env):
        work = Path(tempfile.mkdtemp(prefix="case-", dir=self.root))
        (work / "sandbox.json").write_text(json.dumps({"providers": sandbox}))
        cached = json.dumps({"providers": host or {}})
        self.host.write_text(cached)
        env = {"HOME": str(self.home), "WORK": str(work), "REPO": str(REPO),
               "SMOKE_CALLER_HOME": str(self.root / "caller"), "PYTHON_BIN": sys.executable,
               "PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(self.root),
               "AGENTKIT_ADAPTER_DIR": str(self.adapters), "AGENTKIT_ACCEPTANCE_REQUIRED": "0",
               "AGENTKIT_DISCORD_WEBHOOK": "off", **env}
        result = subprocess.run(["/bin/bash", "-c", 'set -uo pipefail\n'
                                 '. "$REPO/tests/acceptance.sh"\n' + FAKES + CHECK_3 + DEPENDENTS],
                                cwd=work, env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.host.read_text(), cached)
        calls = work / "calls"
        return result.stdout, calls.read_text().splitlines() if calls.exists() else []

    def test_spent_usual_login_skips_each_real_call_even_when_another_has_room(self):
        for source in ("sandbox", "host"):
            for provider, model, labels in HARNESSES:
                with self.subTest(source=source, model=model):
                    record = self.accounts(self.record(100), self.record(10, self.reset + 3600))
                    sandbox, host = ({provider: record}, None) if source == "sandbox" else (
                        {}, {provider: record})
                    output, calls = self.gate(sandbox, host)
                    for label in labels.split("/"):
                        self.assertIn(f"SKIP  {label}: {model} (", output)
                    self.assertIn(f"{provider} subscription window is spent until {self.when}", output)
                    call = model if labels == "3a/3b" else {
                        "grok": "grokbuild.sh", "gemini": "antigravity.sh", "mimo": "opencode.sh"}[model]
                    self.assertNotIn(call, calls)
                    for label in DEPENDENT_LABELS.get(model, ()):
                        self.assertIn(f"SKIP  {label}: required model {model} has a spent "
                                      f"{provider} window until {self.when}", output)

    def test_usual_login_with_room_runs_3a_and_3b(self):
        for source in ("sandbox", "host"):
            for other_used in (10, 100):
                with self.subTest(source=source, other_used=other_used):
                    record = self.accounts(self.record(25), self.record(other_used))
                    sandbox, host = ({"anthropic": record}, None) if source == "sandbox" else (
                        {}, {"anthropic": record})
                    output, calls = self.gate(sandbox, host)
                    self.assertIn("PASS  3a opus (claude): wrote hello.txt", output)
                    self.assertIn("PASS  3b opus (claude): resumed session", output)
                    self.assertEqual(calls.count("opus"), 2)
                    self.assertIn("ATTEMPT_OPUS", output)

    def test_only_the_usual_login_can_supply_a_live_read(self):
        for usual in (None, {"meters": []}):
            with self.subTest(usual=usual):
                snapshot = self.accounts(usual, self.record(10))
                cached = self.accounts(self.record(100), self.record(10))
                output, calls = self.gate({"anthropic": snapshot}, {"anthropic": cached})
                self.assertIn(f"spent until {self.when}", output)
                self.assertNotIn("opus", calls)
        output, calls = self.gate(
            {"anthropic": self.accounts(self.record(25), self.record(10))},
            {"anthropic": self.accounts(self.record(100), self.record(10))})
        self.assertIn("PASS  3a opus (claude)", output)
        self.assertEqual(calls.count("opus"), 2)

    def test_a_refusal_on_the_borrowed_login_still_skips_later_checks(self):
        output, calls = self.gate(
            {"anthropic": self.accounts(self.record(25), self.record(10))}, REFUSED_MODEL="opus")
        self.assertIn("SKIP  3a: required model opus was refused", output)
        self.assertEqual(calls.count("opus"), 1)
        for label in ("4", "4b", "4c", "4d", "31d"):
            self.assertIn(f"SKIP  {label}: required model opus has a spent anthropic window", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
