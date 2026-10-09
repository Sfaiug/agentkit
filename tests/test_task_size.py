"""A task of any size starts, up to three per-round checks; its round budget is three.

Size refuses only past the ceilings: a goal of many numbered points or a long body
starts, alone or in a job.  A round budget over three -- a task's
`rounds`, or `--rounds` at launch or on resume -- is refused before anything starts, in
one sentence naming the rule.  When a run fails at its round budget the hand-back line
says to split, no `continue:` line offers more rounds, and `ak run status --history`
shows rounds per task size so the pattern is visible.

Offline: a temporary HOME with fabricated history rows, scratch (`repo: none`) tasks,
and launches stopped before model calls.
"""

from contextlib import ExitStack, closing, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gc, history, job as jobs, run, status, task
from agentkit import record

SEAT = "size-check"
CFG = {"models": {}, "providers": {}}


class Sandbox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-task-size-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        home = self.root / ".agentkit"
        self.stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "JOBS"):
            self.stack.enter_context(patch.object(config, name, home / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "NO_COLOR": "1", "LANG": "C.UTF-8",
            config.SESSION_ENV: SEAT, config.RUN_DIR_ENV: "", config.UNATTENDED_ENV: "",
            "AK_RUN_ROLE": "", "AK_RUN_LOG": "",
            # a caller that is itself a run would make every launch here a refused worker's worker
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_NOTIFY_SINK": "", config.ACCOUNT_ENV: "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_DISCORD_USER_ID": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        # Most tests stop at admission; the size test also records history before model calls.
        self.drive = self.stack.enter_context(patch.object(run, "drive", return_value=0))

    # --- fixtures ----------------------------------------------------------

    def task(self, name, goal, cmds=("true",), rounds=1):
        path = self.root / name
        path.write_text(f"---\nrepo: none\nrounds: {rounds}\n---\n# Size fixture\n\n"
                        f"## Goal\n{goal}\n\n## Done when\n```bash\n"
                        + "\n".join(cmds) + "\n```\n")
        return path

    def points(self, count):
        return "\n".join(f"{n}. Point {n}." for n in range(1, count + 1))

    def launch(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def failed_at_budget(self):
        return {"state": "fail", "verdict": "FAIL", "rounds": 3,
                "round_summaries": [{}, {}, {}],
                "review_records": [{"kind": "finding", "path": "a.py", "line": 1,
                                    "what": "one", "why": "why", "evidence": {"quote": "one"}},
                                   {"kind": "done"}]}

    def finished(self, run_id, repo, rounds, words, points, at):
        history.start_run(run_id, repo=repo, rounds_used=rounds, started_at=at,
                          task_words=words, task_points=points, task_checks=2)
        history.finish_run(run_id, repo=repo, rounds_used=rounds, started_at=at,
                           finished_at=at + 10, final_state="pass", verdict="PASS")

    # --- size never refuses ------------------------------------------------

    def test_a_task_of_any_size_starts(self):
        goal = self.points(40) + "\n\n" + " ".join(["word"] * 6000)
        task = self.task("big.md", goal, cmds=[f"true # {n}" for n in range(3)])

        def started(cfg, directory, opts, log, **_kw):
            with patch.object(gc, "disk_pressure", return_value=False), \
                    patch.object(run, "collect_usage", side_effect=RuntimeError("before model calls")), \
                    self.assertRaisesRegex(RuntimeError, "before model calls"):
                run.loop(cfg, directory, directory / "task.md", opts, log)
            return 0

        self.drive.side_effect = started
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.drive.call_count, 1)
        self.assertEqual(len(record.run_dirs()), 1)
        row = history.get(record.run_dirs()[0].name)
        self.assertEqual((row["task_words"], row["task_points"], row["task_checks"]),
                         (6128, 40, 3))

    def test_a_job_takes_a_task_of_any_size(self):
        small = self.task("small.md", "One thing.")
        goal = self.points(40) + "\n\n" + " ".join(["word"] * 6000)
        big = self.task("big.md", goal, cmds=[f"true # {n}" for n in range(3)])
        cfg = config.load()
        directory, job = jobs.job_create(cfg, [str(small), str(big)], {"--anyway": False}, None)
        self.assertEqual(len(list(config.JOBS.iterdir())), 1)
        run_dir, _ = jobs.job_start_task(cfg, directory, job["tasks"][1], job["opts"], lambda _: None)
        self.assertEqual((run_dir / "task.md").read_text(), big.read_text())

    # --- the round budget --------------------------------------------------

    def test_task_rounds_over_three_are_refused_with_the_rule(self):
        task = self.task("five.md", "One thing.", rounds=5)
        for extra in ((), ("--anyway",)):
            with self.subTest(extra=extra):
                code, _, err = self.launch(str(task), *extra)
                self.assertEqual(code, 2, err)
                self.assertEqual(err, "ak run: task rounds 5 is over the budget: 3 rounds, then "
                                      "a run goes back to its orchestrator to split or re-scope\n")
        self.assertEqual(record.run_dirs(), [])
        self.drive.assert_not_called()
        # ... and a job refuses the same file before it makes anything
        small = self.task("small.md", "One thing.")
        with self.assertRaisesRegex(config.Error, r"five\.md: task rounds 5 is over the budget"):
            jobs.job_create({}, [str(small), str(task)], {"--anyway": True}, None)
        self.assertEqual(list(config.JOBS.iterdir()), [])

    def test_rounds_over_three_are_refused_at_launch_and_on_resume(self):
        one = self.task("one.md", "One thing.")
        two = self.task("two.md", "Another thing.")
        job_dir = config.JOBS / "job-1"
        job_dir.mkdir(parents=True)
        jobs.save_job(job_dir, {"job_id": "job-1", "tasks": []})
        receipt = (job_dir / "job.json").read_text()
        rule = (r"^--rounds 5 is over the budget: 3 rounds, then a run goes back to its "
                r"orchestrator to split or re-scope$")
        for argv in ([str(one), "--rounds", "5"], [str(one), str(two), "--rounds", "5"],
                     ["resume", "20260101-0000-gone", "--rounds", "5"],
                     ["resume", "job-1", "--rounds", "5"]):
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(config.Error, rule):
                    self.launch(*argv)
        self.assertEqual(record.run_dirs(), [])
        self.assertEqual([path.name for path in config.JOBS.iterdir()], ["job-1"])
        self.assertEqual((job_dir / "job.json").read_text(), receipt)
        self.drive.assert_not_called()
        # the budget itself starts
        code, _, err = self.launch(str(one), "--rounds", "3")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.drive.call_count, 1)

    def test_a_spent_budget_offers_no_more_rounds(self):
        run_dir = config.RUNS / "run-1"
        run_dir.mkdir(parents=True)
        state = {**self.failed_at_budget(), "run_id": run_dir.name, "worktree": str(self.root)}
        record.save_state(run_dir, state)
        self.assertEqual(run.continue_line(state), "")
        with self.assertRaisesRegex(config.Error, r"^run-1 FAILed at its round budget \(3\); "
                                                  r"3 rounds is the budget, so split or "
                                                  r"re-scope the task$"):
            run.cmd_resume([run_dir.name, "--rounds", "3"])
        self.assertEqual(record.read_state(run_dir)["state"], "fail")
        # a budget set below three may still be raised to it, and no further
        below = {**state, "rounds": 1, "round_summaries": [{}]}
        self.assertEqual(run.continue_line(below),
                         f"continue: ak run resume {run_dir.name} --rounds 3")

    # --- the hand-back and the history -------------------------------------

    def test_handback_at_budget_carries_the_split_sentence(self):
        directory = self.root / "run-1"
        directory.mkdir()
        line = run.handback_line(self.failed_at_budget(), directory, CFG)
        self.assertTrue(line.endswith("three rounds spent: split or re-scope"), line)
        # ... while a FAIL with rounds left says nothing about splitting
        below = {**self.failed_at_budget(), "round_summaries": [{}, {}]}
        self.assertNotIn("split or re-scope", run.handback_line(below, directory, CFG))

    def test_history_status_reports_rounds_per_task_size(self):
        self.finished("r1", "atoll", 2, 100, 1, 100)
        self.finished("r2", "atoll", 4, 100, 1, 200)
        self.finished("r3", "atoll", 8, 500, 2, 300)
        self.finished("r4", "atoll", 10, 100, 4, 400)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(status.cmd_status(["--history"]), 0)
        self.assertIn("atoll: last 20 tasks: median 6 rounds · over 400 words: "
                      "median 8 rounds · over 3 points: median 10 rounds",
                      out.getvalue())
        # ... and the default view stays quiet about it
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(status.cmd_status([]), 0)
        self.assertNotIn("last 20 tasks", out.getvalue())

    def test_summary_reads_a_database_from_before_the_size_columns(self):
        database = config.HOME / "history.db"
        connection = sqlite3.connect(database)
        connection.execute(
            "CREATE TABLE runs (run_id TEXT PRIMARY KEY, repo TEXT, executor TEXT, "
            "reviewer TEXT, rounds_used INTEGER, final_state TEXT, verdict TEXT, "
            "started_at REAL, finished_at REAL, executor_seconds REAL, "
            "done_when_seconds REAL, reviewer_seconds REAL, merge_seconds REAL, "
            "total_seconds REAL, executor_tokens INTEGER, reviewer_tokens INTEGER, "
            "peak_rss_mb REAL, session TEXT)")
        connection.execute(
            "INSERT INTO runs (run_id, repo, rounds_used, started_at, finished_at) "
            "VALUES ('old', 'atoll', 3, 1, 2)")
        connection.commit()
        connection.close()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(status.cmd_status(["--history"]), 0)
        self.assertIn("atoll: last 20 tasks: median 3 rounds", out.getvalue())
        with closing(sqlite3.connect(database)) as connection:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(runs)")]
        self.assertIn("task_words", columns)

    def test_changed_files_records_every_file(self):
        repo = self.root / "big"
        repo.mkdir()

        def git(*args):
            proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                                  text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout.strip()

        git("init", "-q")
        (repo / "seed.txt").write_text("seed\n")
        git("add", "-A")
        git("-c", "user.name=size", "-c", "user.email=size@example.invalid",
            "commit", "-qm", "seed")
        base = git("rev-parse", "HEAD")
        for n in range(60):
            (repo / f"file-{n}.txt").write_text("work\n")
        git("add", "-A")
        git("-c", "user.name=size", "-c", "user.email=size@example.invalid",
            "commit", "-qm", "work")
        self.assertEqual(len(run.changed_files(
            {"worktree": str(repo), "base_sha": base})), 60)

    def test_review_only_history_carries_task_size(self):
        run_dir = config.RUNS / "run-review"
        run_dir.mkdir(parents=True)
        (run_dir / "log.txt").touch()
        record.save_state(run_dir, {"run_id": run_dir.name, "state": "running",
                                 "launched_session": None})
        repo = self.root / "repo"
        repo.mkdir()
        wt = self.root / "wt"
        wt.mkdir()
        info = {"state": "OPEN", "headRefOid": "abc", "baseRefName": "main",
                "title": "T", "author": "a", "body": ""}
        seen = {}

        def stop(state, log=None):
            seen.update(state)
            raise RuntimeError("stop after history_start")

        # The empty fake checkout inherits the enclosing repository's Git state.
        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=repo), \
                patch.object(gc, "disk_pressure", return_value=False), \
                patch.object(run, "git", return_value="sha"), \
                patch.object(run, "fetch", return_value=(0, "")), \
                patch.object(run, "git_out", side_effect=AssertionError("real Git in a fake checkout")), \
                patch.object(run, "make_worktree", return_value=(wt, "b")), \
                patch.object(run, "history_start", side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, "stop after history_start"):
                # config.load always fills [defaults]; review_pr reads it since #71
                run.review_pr({"defaults": {"workers": []}}, run_dir, "https://github.com/o/r/pull/1",
                               {"--review": None}, lambda message: None)
        self.assertGreater(seen["task_words"], 0)
        self.assertEqual(seen["task_points"], 0)
        self.assertEqual(seen["task_checks"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
