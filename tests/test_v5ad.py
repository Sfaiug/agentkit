"""v5ad: a run that is already under way is not started a second time.

Two seats once repaired the same red release gate at once because neither could see
the other's in-flight run.  `ak run <task.md>` now refuses -- exit 2, before a run
directory exists -- when a `running` or `queued` run with a live process in the same
repository looks like the same job: a done-when naming the same test file, or four
shared title words.  `--anyway` starts regardless and names the other run in the
preflight; resume, --review-pr and a run's own child launch never check.

Offline: a temporary HOME with fabricated run directories (a live run fakes its
liveness with this process's own pid and identity, the way the loop's own receipts
do), a throwaway git repository with a bare origin, and a patched-out drive step so
no model ever runs.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run

SEAT = "speed-check"    # the seat the fabricated running runs were launched from


class Sandbox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5ad-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        home = self.root / ".agentkit"
        self.stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, home / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "NO_COLOR": "1", "LANG": "C.UTF-8",
            config.SESSION_ENV: SEAT, config.RUN_DIR_ENV: "", config.UNATTENDED_ENV: "",
            "AK_RUN_ROLE": "", "AK_RUN_LOG": "",
            "IDLE_COMPACT_STATE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AGENTKIT_DISCORD_USER_ID": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        # the loop itself never runs: getting past the preflight is what "starts" means
        self.drive = self.stack.enter_context(patch.object(run, "drive", return_value=0))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))

    # --- fixtures ----------------------------------------------------------

    def git(self, *args, cwd):
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def make_repo(self, name):
        """A throwaway git repository with a bare origin, all local."""
        repo = self.root / name
        repo.mkdir()
        self.git("init", "-q", cwd=repo)
        (repo / "README.md").write_text("v5ad fixture\n")
        self.git("add", "-A", cwd=repo)
        self.git("-c", "user.name=v5ad", "-c", "user.email=v5ad@example.invalid",
                 "commit", "-qm", "init", cwd=repo)
        self.git("branch", "-M", "main", cwd=repo)
        bare = self.root / f"{name}-origin.git"
        self.git("init", "-q", "--bare", str(bare), cwd=self.root)
        self.git("remote", "add", "origin", str(bare), cwd=repo)
        self.git("push", "-q", "origin", "main", cwd=repo)
        return repo

    def task_text(self, title, cmds, repo):
        return (f"---\nrepo: {repo}\nbase: main\nrounds: 1\n---\n# {title}\n\n"
                "## Goal\nFixture.\n\n## Done when\n```bash\n" + "\n".join(cmds) + "\n```\n")

    def task(self, name, title, cmds, repo):
        path = self.root / f"{name}.md"
        path.write_text(self.task_text(title, cmds, repo))
        return path

    def running_run(self, name, title, cmds, repo, seat=SEAT, state="running", live=True,
                    stub=False):
        """A fabricated in-flight run; live ones carry this process's own identity.

        stub=True writes the receipt the way capture_launch leaves it: task.md on
        disk, but no repo or title in run.json yet -- the shape every queued run,
        and every run still building its worktree, really has.
        """
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "log.txt").touch()
        (directory / "task.md").write_text(self.task_text(title, cmds, repo))
        owner = dict(run.process_owner()) if live else {"pid": 99999999}
        record = {"run_id": name, "state": state, "verdict": None,
                  "launched_session": seat, "started_at": time.time() - 60,
                  "reported": False, **owner}
        if not stub:
            record.update(title=title, repo=str(repo), scratch=False)
        run.save_state(directory, record)
        return directory

    def launch(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def started_hhmm(self, directory):
        return datetime.fromtimestamp(run.read_state(directory)["started_at"]).strftime("%H:%M")

    # --- the refusal -------------------------------------------------------

    def test_v5ad_same_test_file_refused(self):
        repo = self.make_repo("atoll")
        rival = self.running_run("20260916-1535-repair-gate", "Repair release gate failure",
                                 ["python3 -m pytest tests/test_gate.py -q"], repo,
                                 seat="atoll-speed-check")
        task = self.task("second", "Update checkout flow validation",
                         ["pytest tests/test_gate.py"], repo)
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 2, err)
        self.assertIn("already under way", err)
        self.assertIn(rival.name, err)
        self.assertIn("atoll-speed-check", err)
        self.assertIn("tests/test_gate.py", err)
        self.assertIn(self.started_hhmm(rival), err)
        self.assertIn("--anyway", err)
        self.assertEqual(run.run_dirs(), [rival])
        self.drive.assert_not_called()

    def test_v5ad_shared_title_words_refused(self):
        repo = self.make_repo("atoll")
        rival = self.running_run("20260916-1535-release-gate",
                                 "Repair release gate failed for PR 1728",
                                 ["make check"], repo, state="queued", stub=True)
        task = self.task("second", "Release gate failed PR 1728 repair retry",
                         ["make verify"], repo)
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 2, err)
        self.assertIn(rival.name, err)
        self.assertIn("5 title words", err)
        self.assertEqual(run.run_dirs(), [rival])
        self.drive.assert_not_called()

    def test_v5ad_both_signals_names_only_the_files(self):
        repo = self.make_repo("atoll")
        rival = self.running_run("20260916-1535-release-gate",
                                 "Repair release gate failed for PR 1728",
                                 ["pytest tests/test_gate.py"], repo)
        task = self.task("second", "Release gate failed PR 1728 repair retry",
                         ["pytest tests/test_gate.py"], repo)
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 2, err)
        self.assertIn("shares tests/test_gate.py;", err)
        self.assertNotIn("title words", err)
        self.assertEqual(run.run_dirs(), [rival])
        self.drive.assert_not_called()

    def test_v5ad_missing_started_at_says_unknown(self):
        repo = self.make_repo("atoll")
        rival = self.running_run("20260916-1535-release-gate",
                                 "Repair release gate failed for PR 1728",
                                 ["pytest tests/test_gate.py"], repo)
        record = run.read_state(rival)
        del record["started_at"]
        run.save_state(rival, record)
        task = self.task("second", "Repair release gate failed for PR 1728",
                         ["pytest tests/test_gate.py"], repo)
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 2, err)
        self.assertIn("started ??:??", err)

    def test_v5ad_shared_runner_command_starts(self):
        """`bash tests/smoke.sh` in both done-whens is not the same test file."""
        repo = self.make_repo("agentkit")
        self.running_run("20260916-1535-menu", "Redraw status bar exactly once",
                         ["bash tests/smoke.sh"], repo)
        task = self.task("second", "Copy fetched Mac path exactly once",
                         ["bash tests/smoke.sh"], repo)
        code, _, _ = self.launch(str(task))
        self.assertEqual(code, 0)
        self.assertEqual(len(run.run_dirs()), 2)

    # --- what starts anyway --------------------------------------------------

    def test_v5ad_other_repo_starts(self):
        first = self.make_repo("atoll")
        second = self.make_repo("speedy")
        self.running_run("20260916-1535-release-gate", "Repair release gate failed for PR 1728",
                         ["pytest tests/test_gate.py"], first)
        task = self.task("other", "Repair release gate failed for PR 1728",
                         ["pytest tests/test_gate.py"], second)
        code, _, _ = self.launch(str(task))
        self.assertEqual(code, 0)
        self.assertEqual(self.drive.call_count, 1)
        self.assertEqual(len(run.run_dirs()), 2)

    def test_v5ad_finished_run_starts(self):
        repo = self.make_repo("atoll")
        for word in ("pass", "fail"):
            with self.subTest(state=word):
                rival = config.RUNS / f"20260916-1535-old-{word}"
                rival.mkdir(parents=True)
                (rival / "log.txt").touch()
                title = "Repair release gate failed for PR 1728"
                (rival / "task.md").write_text(self.task_text(title, ["true"], repo))
                run.save_state(rival, {
                    "run_id": rival.name, "title": title, "state": word,
                    "verdict": "PASS" if word == "pass" else "FAIL",
                    "launched_session": SEAT, "started_at": time.time() - 3600,
                    "finished_at": time.time() - 3500, "pid": 99999999,
                    "repo": str(repo), "scratch": False, "reported": False})
                task = self.task(f"again-{word}", title, ["pytest tests/test_gate.py"], repo)
                before = set(run.run_dirs())
                code, _, _ = self.launch(str(task))
                self.assertEqual(code, 0)
                # the launch above is itself a live queued run under the same title:
                # take it back down so the next state does not trip over this one
                for made in run.run_dirs():
                    if made not in before and made != rival:
                        shutil.rmtree(made)

    def test_v5ad_dead_process_starts(self):
        repo = self.make_repo("atoll")
        rival = self.running_run("20260916-1535-release-gate",
                                 "Repair release gate failed for PR 1728",
                                 ["pytest tests/test_gate.py"], repo, live=False)
        self.assertFalse(run.process_active(run.read_state(rival)))
        task = self.task("second", "Repair release gate failed for PR 1728",
                         ["pytest tests/test_gate.py"], repo)
        code, _, _ = self.launch(str(task))
        self.assertEqual(code, 0)
        self.assertEqual(len(run.run_dirs()), 2)

    def test_v5ad_anyway_starts_and_logs(self):
        repo = self.make_repo("atoll")
        rival = self.running_run("20260916-1535-repair-gate", "Repair release gate failure",
                                 ["python3 -m pytest tests/test_gate.py -q"], repo,
                                 seat="atoll-speed-check")
        task = self.task("second", "Update checkout flow validation",
                         ["pytest tests/test_gate.py"], repo)
        code, _, _ = self.launch(str(task), "--anyway")
        self.assertEqual(code, 0)
        made = [d for d in run.run_dirs() if d != rival]
        self.assertEqual(len(made), 1, [d.name for d in run.run_dirs()])
        log = (made[0] / "log.txt").read_text()
        self.assertIn(f"--- preflight: started alongside {rival.name} (--anyway)", log)

    def test_v5ad_unresolvable_repo_starts(self):
        """A repository git cannot resolve is not a duplicate: the launch proceeds."""
        task = self.root / "noroot.md"
        task.write_text("---\nrounds: 1\n---\n# Task\n\n## Done when\n```bash\ntrue\n```\n")
        # the hostile Popen mock breaks every git call the preflight check could make
        with patch.object(run.subprocess, "Popen", **{"return_value.pid": 99999999}), \
                patch.object(run, "preflight", return_value=None), \
                redirect_stdout(io.StringIO()):
            code = run.main([str(task), "--bg"])
        self.assertEqual(code, 0)
        self.assertEqual(run.read_state(run.run_dirs()[-1])["pid"], 99999999)

    def test_v5ad_resume_never_checks(self):
        repo = self.make_repo("atoll")
        title = "Repair release gate failed for PR 1728"
        rival = self.running_run("20260916-1535-release-gate", title,
                                 ["pytest tests/test_gate.py"], repo)
        target = config.RUNS / "20260916-1500-stalled-gate"
        target.mkdir(parents=True)
        (target / "log.txt").touch()
        (target / "task.md").write_text(self.task_text(title, ["make verify"], repo))
        run.save_state(target, {
            "run_id": target.name, "title": title, "state": "interrupted",
            "recovery_pending": True, "interruption_reason": "fixture stop",
            "launched_session": SEAT, "started_at": time.time() - 3600,
            "repo": str(repo), "scratch": False, "reported": False})
        code, _, _ = self.launch("resume", target.name)
        self.assertEqual(code, 0)
        self.assertEqual(self.drive.call_count, 1)
        self.assertEqual(run.read_state(rival)["state"], "running")


if __name__ == "__main__":
    unittest.main(verbosity=2)
