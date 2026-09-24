"""A task has one behaviour and three rounds, and the loop refuses a bigger one at launch.

`ak run` exits 2 before a run directory exists when the task's goal holds more than
three numbered points, its body holds more than 500 words outside the checks block,
or its checks block holds more than six commands -- naming the rule and the count in
one sentence.  `--anyway` does not waive it; it only starts a run beside one already
under way.  A job refuses per file the same way.  A round budget over three -- a task's
`rounds`, or `--rounds` at launch or on resume -- is refused before anything starts, in
one sentence naming the rule.  When a run fails at its round budget the hand-back line
says to split, no `continue:` line offers more rounds, and `ak run status --history`
shows rounds per task size so the pattern is visible.

Offline: a temporary HOME with fabricated history rows, scratch (`repo: none`) tasks,
and a patched-out drive step so no model ever runs.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
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
from agentkit import config, history, run

SEAT = "size-check"
CFG = {"models": {}, "providers": {}}


class Sandbox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".task-size-", dir=REPO)
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
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_DISCORD_USER_ID": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        # the loop itself never runs: getting past the launch checks is what "starts" means
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

    def words_outside_checks(self, path):
        """The body's word count with the fenced checks block cut out, by hand."""
        body = run.parse_task(path)[1]
        start = body.index("```")
        end = body.index("```", start + 3) + 3
        return len((body[:start] + body[end:]).split())

    def launch(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def failed_at_budget(self):
        return {"state": "fail", "verdict": "FAIL", "rounds": 3,
                "round_summaries": [{}, {}, {}],
                "findings": "VERDICT: FAIL\n\n## Findings\n- a.py:1 - one - why\n"}

    def finished(self, run_id, repo, rounds, words, points, at):
        history.start_run(run_id, repo=repo, rounds_used=rounds, started_at=at,
                          task_words=words, task_points=points, task_checks=2)
        history.finish_run(run_id, repo=repo, rounds_used=rounds, started_at=at,
                           finished_at=at + 10, final_state="pass", verdict="PASS")

    # --- the refusal -------------------------------------------------------

    def test_four_point_goal_is_refused_with_the_count(self):
        task = self.task("four.md", self.points(4))
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 2, err)
        self.assertIn("4 numbered goal points", err)
        self.assertNotIn("--anyway", err)       # no way past it is offered
        self.assertEqual(run.run_dirs(), [])
        self.drive.assert_not_called()

    def test_long_body_is_refused_with_the_count(self):
        task = self.task("long.md", " ".join(["word"] * 600))
        expected = self.words_outside_checks(task)
        self.assertGreater(expected, 500)
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 2, err)
        self.assertIn(f"{expected} words outside the checks block", err)
        self.assertNotIn("--anyway", err)
        self.assertEqual(run.run_dirs(), [])
        self.drive.assert_not_called()

    def test_seven_checks_are_refused_with_the_count(self):
        task = self.task("seven.md", "One thing.", cmds=[f"true # {n}" for n in range(7)])
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 2, err)
        self.assertIn("7 checks", err)
        self.assertNotIn("--anyway", err)
        self.assertEqual(run.run_dirs(), [])
        self.drive.assert_not_called()

    def test_a_task_at_the_limits_starts(self):
        task = self.task("limits.md", self.points(3),
                         cmds=[f"true # {n}" for n in range(6)])
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.drive.call_count, 1)
        self.assertEqual(len(run.run_dirs()), 1)

    def test_words_inside_the_checks_block_are_not_counted(self):
        task = self.task("echo.md", "One thing.",
                         cmds=["echo " + " ".join(["word"] * 600)])
        code, _, err = self.launch(str(task))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.drive.call_count, 1)

    # --- no bypass ---------------------------------------------------------

    def test_anyway_does_not_waive_the_size_limit(self):
        task = self.task("anyway.md", self.points(4))
        code, _, err = self.launch(str(task), "--anyway")
        self.assertEqual(code, 2, err)
        self.assertIn("4 numbered goal points", err)
        self.assertEqual(run.run_dirs(), [])
        self.drive.assert_not_called()

    def test_a_job_refuses_an_oversize_task_per_file(self):
        small = self.task("small.md", "One thing.")
        big = self.task("big.md", self.points(4))
        with self.assertRaisesRegex(config.Error, r"big\.md.*4 numbered goal points"):
            run.job_create({}, [str(small), str(big)], {"--anyway": False}, None)
        self.assertEqual(list(config.JOBS.iterdir()), [])

    def test_a_job_anyway_still_refuses_an_oversize_task(self):
        small = self.task("small.md", "One thing.")
        big = self.task("big.md", self.points(4))
        with self.assertRaisesRegex(config.Error, r"big\.md.*4 numbered goal points"):
            run.job_create({}, [str(small), str(big)], {"--anyway": True}, None)
        self.assertEqual(list(config.JOBS.iterdir()), [])

    # --- the round budget --------------------------------------------------

    def test_task_rounds_over_three_are_refused_with_the_rule(self):
        task = self.task("five.md", "One thing.", rounds=5)
        for extra in ((), ("--anyway",)):
            with self.subTest(extra=extra):
                code, _, err = self.launch(str(task), *extra)
                self.assertEqual(code, 2, err)
                self.assertEqual(err, "ak run: task rounds 5 is over the budget: 3 rounds, then "
                                      "a run goes back to its orchestrator to split or re-scope\n")
        self.assertEqual(run.run_dirs(), [])
        self.drive.assert_not_called()
        # ... and a job refuses the same file before it makes anything
        small = self.task("small.md", "One thing.")
        with self.assertRaisesRegex(config.Error, r"five\.md: task rounds 5 is over the budget"):
            run.job_create({}, [str(small), str(task)], {"--anyway": True}, None)
        self.assertEqual(list(config.JOBS.iterdir()), [])

    def test_rounds_over_three_are_refused_at_launch_and_on_resume(self):
        one = self.task("one.md", "One thing.")
        two = self.task("two.md", "Another thing.")
        job_dir = config.JOBS / "job-1"
        job_dir.mkdir(parents=True)
        run.save_job(job_dir, {"job_id": "job-1", "tasks": []})
        receipt = (job_dir / "job.json").read_text()
        rule = (r"^--rounds 5 is over the budget: 3 rounds, then a run goes back to its "
                r"orchestrator to split or re-scope$")
        for argv in ([str(one), "--rounds", "5"], [str(one), str(two), "--rounds", "5"],
                     ["resume", "20260101-0000-gone", "--rounds", "5"],
                     ["resume", "job-1", "--rounds", "5"]):
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(config.Error, rule):
                    self.launch(*argv)
        self.assertEqual(run.run_dirs(), [])
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
        run.save_state(run_dir, state)
        self.assertEqual(run.continue_line(state), "")
        with self.assertRaisesRegex(config.Error, r"^run-1 FAILed at its round budget \(3\); "
                                                  r"3 rounds is the budget, so split or "
                                                  r"re-scope the task$"):
            run.cmd_resume([run_dir.name, "--rounds", "3"])
        self.assertEqual(run.read_state(run_dir)["state"], "fail")
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
            self.assertEqual(run.cmd_status(["--history"]), 0)
        self.assertIn("atoll: last 20 tasks: median 6 rounds · over 400 words: "
                      "median 8 rounds · over 3 points: median 10 rounds",
                      out.getvalue())
        # ... and the default view stays quiet about it
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status([]), 0)
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
            self.assertEqual(run.cmd_status(["--history"]), 0)
        self.assertIn("atoll: last 20 tasks: median 3 rounds", out.getvalue())
        columns = [row[1] for row in sqlite3.connect(database).execute(
            "PRAGMA table_info(runs)")]
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
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "running",
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

        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=repo), \
                patch.object(run, "disk_pressure", return_value=False), \
                patch.object(run, "git", return_value="sha"), \
                patch.object(run, "make_worktree", return_value=(wt, "b")), \
                patch.object(run, "history_start", side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, "stop after history_start"):
                run.review_pr({}, run_dir, "https://github.com/o/r/pull/1",
                               {"--review": None}, lambda message: None)
        self.assertGreater(seen["task_words"], 0)
        self.assertEqual(seen["task_points"], 0)
        self.assertEqual(seen["task_checks"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
