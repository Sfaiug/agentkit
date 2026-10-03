"""Smoke's retry checks spend the production delays on a test clock, without real waits."""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import re
import runpy
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import call, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, record, run

SMOKE = (REPO / "tests/smoke.sh").read_text()


class TransientBackoffClock(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-backoff-clock-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("AGENTKIT_", "AK_")) and key not in (
                        "TMUX", "PYTHONPATH", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME",
                        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "GH_CONFIG_DIR", "OPENCODE_CONFIG",
                        "OPENCODE_CONFIG_DIR")}
        self.env.update(HOME=str(self.root), TMPDIR=str(self.root), WORK=str(self.root),
                        REPO=str(REPO), PATH=f"{REPO / 'bin'}:{os.environ['PATH']}",
                        PYTHONDONTWRITEBYTECODE="1", AK_MAX_RUNS="0", AK_RUN_DEPTH="0",
                        AGENTKIT_DISCORD_WEBHOOK="off", AK_NOTIFY_SINK="dry-run")
        self.stack.enter_context(patch.dict(os.environ, self.env, clear=True))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.object(run.history, "close_step"))
        self.stack.enter_context(patch.object(run.history, "open_step"))

    def clock_script(self):
        script = re.search(r"<<'PY_RETRY_CLOCK'\n(.*?)\nPY_RETRY_CLOCK", SMOKE, re.S)
        self.assertIsNotNone(script, "smoke's retry runs still use the real clock")
        return script[1]

    def test_normal_runs_keep_the_production_schedule_and_sleep(self):
        self.assertEqual(run.TRANSIENT_BACKOFF, (60, 300, 900, 1800, 3600))
        self.assertEqual([run.transient_delay(i) for i in range(1, 8)],
                         [60, 300, 900, 1800, 3600, 3600, 3600])
        out = self.root / "normal" / "round-1" / "executor"
        with patch.object(run.time, "sleep") as sleep:
            for attempt in (1, 2):
                run.transient_wait(out, run.transient_delay(attempt))
        self.assertEqual(sleep.call_args_list, [call(60), call(300)])

    def test_test_clock_advances_deadlines_and_leaves_other_waits_alone(self):
        script = self.clock_script()
        real_clock, real_wait = run.time, run.transient_wait
        run_dir = self.root / "clock-run"
        run_dir.mkdir()
        record.save_state(run_dir, {"state": "running"})
        out = run_dir / "round-1" / "executor"

        def launch(path, run_name, **_kw):
            self.assertEqual((path, run_name), (str(REPO / "bin/ak"), "__main__"))
            self.assertIs(run.time, real_clock)
            deadlines = []
            for delay in (60, 300, 1):
                run.transient_wait(out, delay)
                wait = record.read_state(run_dir)["transient_wait"]
                self.assertEqual(wait["pid"], os.getpid())
                deadlines.append(wait["until"])
                self.assertIs(run.time, real_clock)
            self.assertEqual(deadlines[1] - deadlines[0], 300)
            self.assertEqual(deadlines[2] - deadlines[1], 1)
            run.time.sleep(0.25)

        output = io.StringIO()
        with patch.object(sys, "argv", ["-", str(REPO / "bin/ak"), "run"]), \
                patch.object(runpy, "run_path", side_effect=launch), \
                patch.object(real_clock, "sleep") as sleep, redirect_stdout(output):
            exec(script, {})
        sleep.assert_called_once_with(0.25)
        self.assertIs(run.transient_wait, real_wait)
        self.assertEqual(output.getvalue().splitlines(), [
            "test clock advanced 60s", "test clock advanced 300s", "test clock advanced 1s"])

    def test_smoke_9a_and_9b_finish_without_the_backoff(self):
        self.clock_script()  # refuse the unmodified check before it can sleep for six minutes
        helpers = SMOKE[SMOKE.index("newrepo() {"):SMOKE.index('\necho "workdir: $WORK"')]
        launch = SMOKE[SMOKE.index("# --- fakes for checks 9 and 10:"):
                       SMOKE.index("# Checks 1 to 5,")]
        checks = SMOKE[SMOKE.index("# --- 9: transient worker failures"):
                       SMOKE.index("# --- 10:")]
        script = ('set -uo pipefail\n. "$REPO/tests/acceptance.sh"\n' + helpers + "\n"
                  + launch + "\n" + checks + "\nfinish\n")
        # Only these two checks run, on their own HOME and repos. A regression must end
        # their process group too, rather than leave the old six-minute wait behind.
        proc = subprocess.Popen(["bash", "-c", script], cwd=self.root, env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, start_new_session=True)
        try:
            output = proc.communicate(timeout=60)[0]
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            output = proc.communicate()[0]
            self.fail("retry checks did not finish within 60 seconds:\n" + output)
        logs = {tag: (self.root / f"retry-{tag}.log").read_text() for tag in ("exec", "review")}
        self.assertEqual(proc.returncode, 0, output + "\n" + "\n".join(logs.values()))
        self.assertIn("PASS  9a ", output)
        self.assertIn("PASS  9b ", output)
        self.assertIn("2 passed, 0 failed, 0 skipped", output)
        self.assertEqual(re.findall(r"^test clock advanced (\d+)s$", logs["exec"], re.M),
                         ["60", "300"])
        self.assertIn("retrying in 60s", logs["exec"])
        self.assertIn("retrying in 300s", logs["exec"])
        self.assertEqual((self.root / "ad-retry-exec/claude.n").read_text().strip(), "3")
        self.assertIn("reviewer fell back to spark", logs["review"])
        self.assertEqual((self.root / "ad-retry-review/codex.n").read_text().strip(), "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
