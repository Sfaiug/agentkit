"""Merged changes become live on the project's probe; deadline failures use the same break.

Offline: temporary HOME and repositories, fake checks and seats, and an injected timeout.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, orch, record, run, watch

NOW = 2000000
PR = "https://github.com/acme/widget/pull/7"
SEAT = "fix-api"


class HealthAfterMerge(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-health-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        env = {key: value for key, value in os.environ.items()
               if key not in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG")}
        env.update(HOME=str(self.root), AK_RUN_DEPTH="0", AK_MAX_RUNS="0")
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        self.repo = self.root / "widget"
        self.repo.mkdir()
        self.git("init", "-q")
        self.ci = ("passed", None, None)
        self.checks = stack.enter_context(patch.object(
            watch, "after_merge_status", side_effect=lambda *_args: self.ci))
        self.rows = [{"name": SEAT, "created": 100, "exited": False}]
        self.lines = []
        self.logs = []
        stack.enter_context(patch.object(orch, "sessions", lambda: list(self.rows)))
        stack.enter_context(patch.object(orch, "find", lambda name: next(
            (seat for seat in self.rows if seat["name"] == name), None)))
        stack.enter_context(patch.object(watch, "type_at_prompt", self.send))
        self.probes = stack.enter_context(patch.object(
            watch, "health_command", wraps=watch.health_command))
        self.state = {}

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                               *args], cwd=self.repo, capture_output=True, text=True,
                              check=True, timeout=10).stdout.strip()

    def declare(self, command):
        line = f"health: {command}\n" if command is not None else ""
        (self.repo / "AGENTS.md").write_text(f"---\n{line}---\n# Widget\n")
        self.git("add", "AGENTS.md")
        self.git("commit", "-qm", "Declare live probe")
        return self.git("rev-parse", "HEAD")

    def remote_merge(self, command):
        self.declare(None)
        self.git("branch", "-M", "main")
        origin = self.root / "origin.git"
        hub = self.root / "hub"
        self.git("clone", "-q", "--bare", str(self.repo), str(origin))
        self.git("remote", "add", "origin", str(origin))
        self.git("clone", "-q", str(origin), str(hub))
        (hub / "AGENTS.md").write_text(f"---\nhealth: {command}\n---\n")
        self.git("-C", str(hub), "add", "AGENTS.md")
        self.git("-C", str(hub), "commit", "-qm", "Merge pull request #7")
        self.git("-C", str(origin), "fetch", "-q", str(hub), "HEAD:refs/heads/main")
        sha = self.git("-C", str(hub), "rev-parse", "HEAD")
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("cat-file", "-e", f"{sha}^{{commit}}")
        return sha

    def merged(self, sha, name="run-a", age=600, seat=SEAT):
        directory = config.RUNS / name
        directory.mkdir()
        record.save_state(directory, {
            "run_id": name, "state": "pass", "verdict": "PASS", "merged": True,
            "pr": PR, "merge_sha": sha, "target": "origin/main", "launched_session": seat,
            "repo": str(self.repo), "worktree": str(self.root / "dropped-worktree"),
            "finished_at": NOW - age})
        history.start_run(name, repo=self.repo, started_at=NOW - age - 60)
        history.finish_run(name, final_state="pass", finished_at=NOW - age)
        return directory

    def send(self, seat, line, log, **_kw):
        self.lines.append((seat["name"], line))
        return True

    def tick(self, now=NOW, dry_run=False):
        watch.after_merge_checks(self.state, dry_run, self.logs.append, now=now)

    def test_first_pass_uses_merge_declaration_original_checkout_and_sha(self):
        sha = self.declare("printf '%s\\n%s\\n' \"$PWD\" \"$AK_MERGE_SHA\" > live-proof")
        directory = self.merged(sha)
        (self.repo / "AGENTS.md").write_text("---\nhealth: exit 99\n---\n")
        self.tick()
        self.assertEqual((self.repo / "live-proof").read_text().splitlines(),
                         [str(self.repo), sha])
        st = record.read_state(directory)
        self.assertEqual((st["live_at"], st["finished_at"]), (NOW, NOW - 600))
        self.assertEqual(history.get("run-a")["live_at"], NOW)
        self.assertEqual(self.lines, [(SEAT, f"run run-a is live: {PR}.")])
        self.tick(now=NOW + 60)
        self.assertEqual((self.probes.call_count, len(self.lines)), (1, 1))
        self.assertEqual(record.read_state(directory)["live_at"], NOW)

    def test_remote_merge_commit_is_fetched_without_changing_the_checkout(self):
        sha = self.remote_merge("echo \"$AK_MERGE_SHA\" > live-proof")
        head = self.git("rev-parse", "HEAD")
        agents = (self.repo / "AGENTS.md").read_text()
        directory = self.merged(sha)
        with record.record(directory) as current:
            current.pop("merge_sha")
        with patch.object(watch, "gh_json", return_value=({"mergeCommit": {"oid": sha}}, "")):
            self.tick()
        self.assertEqual(self.probes.call_count, 1)
        self.assertEqual((self.repo / "live-proof").read_text().strip(), sha)
        self.assertEqual(record.read_state(directory)["live_at"], NOW)
        self.assertEqual(history.get("run-a")["live_at"], NOW)
        self.assertEqual(self.lines, [(SEAT, f"run run-a is live: {PR}.")])
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), agents)

    def test_failed_fetch_retries_the_remote_declaration_next_tick(self):
        sha = self.remote_merge("exit 0")
        directory = self.merged(sha)
        self.git("remote", "set-url", "origin", str(self.root / "unavailable.git"))
        self.tick()
        self.probes.assert_not_called()
        self.assertNotIn("live_at", record.read_state(directory))
        self.assertEqual(self.lines, [])
        self.git("remote", "set-url", "origin", str(self.root / "origin.git"))
        self.tick(now=NOW + 60)
        self.assertEqual(self.probes.call_count, 1)
        self.assertEqual(record.read_state(directory)["live_at"], NOW + 60)

    def test_dry_run_does_not_fetch_a_missing_merge_commit(self):
        sha = self.remote_merge("exit 0")
        directory = self.merged(sha)
        before = record.read_state(directory)
        with patch.object(run, "fetch") as fetch:
            self.tick(dry_run=True)
        fetch.assert_not_called()
        self.probes.assert_not_called()
        self.assertEqual(record.read_state(directory), before)
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("cat-file", "-e", f"{sha}^{{commit}}")

    def test_failure_repeats_until_deployment_passes(self):
        sha = self.declare("echo deployment pending; test -f deployed")
        directory = self.merged(sha)
        self.tick()
        self.tick(now=NOW + 60)
        self.assertEqual(self.probes.call_count, 2)
        self.assertEqual(self.lines, [])
        self.assertNotIn("live_at", record.read_state(directory))
        self.assertIsNone(history.get("run-a")["live_at"])
        (self.repo / "deployed").touch()
        self.tick(now=NOW + 120)
        self.assertEqual(record.read_state(directory)["live_at"], NOW + 120)
        self.assertEqual(len(self.lines), 1)
        self.tick(now=NOW + 180)
        self.assertEqual(self.probes.call_count, 3)

    def test_one_probe_per_merge_commit_per_tick_records_each_run(self):
        sha = self.declare("exit 0")
        first = self.merged(sha)
        second = self.merged(sha, name="run-b", seat="fix-ui")
        self.rows.append({"name": "fix-ui", "created": 200, "exited": False})
        self.tick()
        self.assertEqual(self.probes.call_count, 1)
        self.assertEqual([seat for seat, _ in self.lines], [SEAT, "fix-ui"])
        for directory in (first, second):
            self.assertEqual(record.read_state(directory)["live_at"], NOW)
            self.assertEqual(history.get(directory.name)["live_at"], NOW)

    def test_deadline_failure_is_told_once_with_last_stdout_and_stderr(self):
        sha = self.declare("for i in {1..20}; do echo line-$i; done; echo still broken >&2; exit 1")
        directory = self.merged(sha, age=watch.AFTER_MERGE_WINDOW - 1)
        self.tick()
        self.assertEqual(self.lines, [])
        self.tick(now=NOW + 1)
        self.assertEqual(len(self.lines), 1)
        seat, line = self.lines[0]
        self.assertEqual(seat, SEAT)
        self.assertIn("health:", line)
        self.assertIn("line-20\nstill broken", line)
        self.assertNotIn("\nline-1\n", line)
        self.assertEqual(self.state["after_merge"][watch.after_merge_repo(PR)[3]]["notified"], sha)
        self.assertNotIn("health", record.read_state(directory))
        self.tick(now=NOW + 2)
        self.tick(now=NOW + 3)
        self.assertEqual((self.probes.call_count, len(self.lines)), (1, 1))

    def test_expired_failure_waits_for_a_seat_without_losing_evidence(self):
        sha = self.declare("echo deployment missing; exit 1")
        self.merged(sha, age=watch.AFTER_MERGE_WINDOW - 1)
        self.tick()
        self.rows = []
        self.tick(now=NOW + 2)
        key = watch.after_merge_repo(PR)[3]
        self.assertIn("deployment missing", self.state["after_merge"][key]["pending"]["line"])
        self.state = watch.load_state()
        self.tick(now=NOW + 3)
        self.assertEqual(self.lines, [])
        self.rows = [{"name": SEAT, "created": 100, "exited": False}]
        self.tick(now=NOW + 4)
        self.tick(now=NOW + 5)
        self.assertEqual((self.probes.call_count, len(self.lines)), (1, 1))
        self.assertIn("deployment missing", self.lines[0][1])

    def test_live_notice_retries_its_composer_after_the_window_without_a_new_probe(self):
        sha = self.declare("exit 0")
        directory = self.merged(sha)
        calls = []
        mark = {"line": "live notice", "seat": 100}

        def compose(seat, line, log, typed=None, receipt=lambda mark: None, **_kw):
            calls.append(typed)
            if typed is None:
                receipt(mark)
                return False
            return self.send(seat, line, log)

        with patch.object(watch, "type_at_prompt", compose):
            self.tick()
            self.assertNotIn("live_notified", record.read_state(directory))
            self.tick(now=NOW + watch.AFTER_MERGE_WINDOW)
            self.tick(now=NOW + watch.AFTER_MERGE_WINDOW + 1)
        self.assertEqual(calls, [None, mark])
        self.assertEqual((self.probes.call_count, len(self.lines)), (1, 1))
        self.assertEqual(record.read_state(directory)["live_at"], NOW)

    def test_health_failure_and_check_failure_share_one_episode(self):
        sha = self.declare("echo deployment missing; exit 1")
        self.merged(sha, age=watch.AFTER_MERGE_WINDOW - 1)
        self.ci = ("failed", "release-gate", PR + "/checks")
        self.tick()
        self.assertEqual(len(self.lines), 1)
        self.tick(now=NOW + 2)
        self.tick(now=NOW + 3)
        self.assertEqual(len(self.lines), 1)
        self.assertIn("release-gate", self.lines[0][1])

    def test_absent_declaration_at_merge_preserves_check_behavior(self):
        sha = self.declare(None)
        directory = self.merged(sha)
        (self.repo / "AGENTS.md").write_text("---\nhealth: exit 0\n---\n")
        self.tick()
        self.probes.assert_not_called()
        self.assertEqual(self.lines, [])
        self.assertNotIn("live_at", record.read_state(directory))
        self.ci = ("failed", "release-gate", PR + "/checks")
        self.tick()
        self.assertEqual(self.lines, [(SEAT, watch.after_merge_line(
            "release-gate", "main", PR + "/checks"))])

    def test_dry_run_neither_runs_health_nor_records_live(self):
        sha = self.declare("exit 0")
        directory = self.merged(sha)
        before = record.read_state(directory)
        self.tick(dry_run=True)
        self.probes.assert_not_called()
        self.assertEqual(record.read_state(directory), before)
        self.assertEqual(self.lines, [])
        self.assertIsNone(history.get("run-a")["live_at"])

    def test_timeout_kills_the_whole_group_and_bounds_reaping(self):
        proc = Mock(pid=12345, returncode=None)
        proc.wait.side_effect = [subprocess.TimeoutExpired("health", watch.HEALTH_TIMEOUT),
                                 subprocess.TimeoutExpired("health", 1)]

        def start(argv, **kwargs):
            self.assertEqual(argv, ["bash", "-c", "probe"])
            self.assertEqual(kwargs["cwd"], self.repo)
            self.assertEqual(kwargs["env"]["AK_MERGE_SHA"], "a" * 40)
            self.assertTrue(kwargs["start_new_session"])
            kwargs["stdout"].write(b"waiting for deployment\n")
            return proc

        with patch.object(watch.subprocess, "Popen", side_effect=start), \
                patch.object(watch.os, "killpg") as kill:
            passed, output = self.probes(self.repo, "a" * 40, "probe")
        self.assertFalse(passed)
        self.assertIn("waiting for deployment", output)
        self.assertIn("timed out", output)
        kill.assert_called_once_with(proc.pid, signal.SIGKILL)
        self.assertEqual([call.kwargs["timeout"] for call in proc.wait.call_args_list],
                         [watch.HEALTH_TIMEOUT, 1])


if __name__ == "__main__":
    unittest.main()
