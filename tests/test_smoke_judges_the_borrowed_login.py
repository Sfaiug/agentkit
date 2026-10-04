"""Smoke's real calls judge the usual login, even when another subscription has room.

Check 3 is extracted from smoke.sh and run with fake workers and adapters in a temporary
HOME. Neither the caller's state nor a real provider is touched.
"""

import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import time
import unittest

from test_update_gate_every_harness import ADAPTER, BINARIES, MANIFESTS, unboxed_worker

REPO = Path(__file__).resolve().parents[1]
SMOKE = (REPO / "tests/smoke.sh").read_text()
CHECK_3 = (SMOKE[SMOKE.index("model_unavailable()"):SMOKE.index("reprobe()")]
           + SMOKE[SMOKE.index("# --- 3:"):SMOKE.index("# --- 3a:")])
DEPENDENTS = ('\nif skip_spent 4/4b/4c/4d/31d opus; then :; else echo ATTEMPT_OPUS; fi\n'
              'if skip_spent 31e astra; then :; else echo ATTEMPT_ASTRA; fi\nfinish\n')
HARNESSES = (("anthropic", "opus", "claude"), ("openai", "astra", "codex"),
             ("meta", "spark", "muse"), ("xai", "grok", "grokbuild"),
             ("google", "gemini", "antigravity"), ("mimo", "mimo", "opencode"))
DEPENDENT_LABELS = {"opus": ("4", "4b", "4c", "4d", "31d"), "astra": ("31e",)}
FAKES = 'ak() { cat "$WORK/sandbox.json"; }\n'



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
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        for tool in ("bash", "mkdir", "cat", "grep", "sed", "tail"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        for harness in MANIFESTS:
            shutil.copy2(REPO / "adapters" / f"{harness}.toml", self.adapters)
            adapter = self.adapters / f"{harness}.sh"
            adapter.write_text(ADAPTER)
            adapter.chmod(0o755)
            (self.bin / BINARIES[harness]).touch(mode=0o755)
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
        for harness in MANIFESTS:
            turn = ("1 Claude AI usage limit reached" if harness == "claude"
                    and env.get("REFUSED_MODEL") == "opus" else "0 DONE")
            for suffix, answer in (("auth", "0 fixture: logged in"), ("turn", turn),
                                   ("said", ""), ("events", "")):
                (work / f"{harness}.{suffix}").write_text(answer + "\n")
        env = {"HOME": str(self.home), "WORK": str(work), "REPO": str(REPO),
               "PYTHONPATH": unboxed_worker(self.root),
               "SMOKE_CALLER_HOME": str(self.root / "caller"), "PYTHON_BIN": sys.executable,
               "PATH": str(self.bin), "FIXTURE": str(work), "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(self.root),
               "AGENTKIT_ADAPTER_DIR": str(self.adapters), "AGENTKIT_ACCEPTANCE_REQUIRED": "0",
               "AGENTKIT_DISCORD_WEBHOOK": "off", **env}
        result = subprocess.run(["/bin/bash", "-c", 'set -uo pipefail\n'
                                 '. "$REPO/tests/acceptance.sh"\n' + FAKES + CHECK_3 + DEPENDENTS],
                                cwd=work, env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.host.read_text(), cached)
        calls = [p.stem for p in work.glob("*.runs") for _ in p.read_text().splitlines()]
        return result.stdout, calls

    def test_spent_usual_login_skips_each_real_call_even_when_another_has_room(self):
        for source in ("sandbox", "host"):
            for provider, model, harness in HARNESSES:
                with self.subTest(source=source, model=model):
                    record = self.accounts(self.record(100), self.record(10, self.reset + 3600))
                    sandbox, host = ({provider: record}, None) if source == "sandbox" else (
                        {}, {provider: record})
                    output, calls = self.gate(sandbox, host)
                    self.assertIn(f"SKIP  3 {harness}:", output)
                    self.assertIn(f"{provider} subscription window is spent until {self.when}", output)
                    self.assertNotIn(harness, calls)
                    for label in DEPENDENT_LABELS.get(model, ()):
                        self.assertIn(f"SKIP  {label}: required model {model} has a spent "
                                      f"{provider} window until {self.when}", output)

    def test_usual_login_with_room_runs_both_contract_turns(self):
        for source in ("sandbox", "host"):
            for other_used in (10, 100):
                with self.subTest(source=source, other_used=other_used):
                    record = self.accounts(self.record(25), self.record(other_used))
                    sandbox, host = ({"anthropic": record}, None) if source == "sandbox" else (
                        {}, {"anthropic": record})
                    output, calls = self.gate(sandbox, host)
                    self.assertIn("PASS  3 claude: wrote the file", output)
                    self.assertIn("resumed and recalled the file", output)
                    self.assertEqual(calls.count("claude"), 2)
                    self.assertIn("ATTEMPT_OPUS", output)

    def test_only_the_usual_login_can_supply_a_live_read(self):
        for usual in (None, {"meters": []}):
            with self.subTest(usual=usual):
                snapshot = self.accounts(usual, self.record(10))
                cached = self.accounts(self.record(100), self.record(10))
                output, calls = self.gate({"anthropic": snapshot}, {"anthropic": cached})
                self.assertIn(f"spent until {self.when}", output)
                self.assertNotIn("claude", calls)
        output, calls = self.gate(
            {"anthropic": self.accounts(self.record(25), self.record(10))},
            {"anthropic": self.accounts(self.record(100), self.record(10))})
        self.assertIn("PASS  3 claude:", output)
        self.assertEqual(calls.count("claude"), 2)

    def test_a_refusal_on_the_borrowed_login_still_skips_later_checks(self):
        output, calls = self.gate(
            {"anthropic": self.accounts(self.record(25), self.record(10))}, REFUSED_MODEL="opus")
        self.assertIn("SKIP  3 claude: was refused", output)
        self.assertEqual(calls.count("claude"), 1)
        for label in ("4", "4b", "4c", "4d", "31d"):
            self.assertIn(f"SKIP  {label}: required model opus has a spent anthropic window", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
