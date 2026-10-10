"""A seat's launch names no model, no place in the queue and no second run of a change under way:
`--exec`, `--review`, `--first` and `--anyway` are refused from a seat, since ak picks the models
by budget, decides what goes first and refuses the rival itself.  A seat is a recorded session;
a shell naming none is no seat, and outside a seat the flags stand, as they do in the queued
child `spawn_bg` starts under the seat's name (a job's rerun on the next executor).

Offline: the bin/ak entry point with a temporary HOME and launch effects mocked out.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, job, run

AK_MAIN = runpy.run_path(str(REPO / "bin/ak"))["main"]
SEAT = "fix-api"
PR = "https://github.com/acme/widget/pull/7"


class SeatVerbs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-seat-verbs-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = self.root / ".agentkit"
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "JOBS"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        self.env = stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", config.SESSION_ENV: SEAT,
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": ""}))
        config.ensure_dirs()
        config.save_session(config.load(), SEAT, "opus", ["opus"], {"reviewers": ["astra"]})
        self.prepare = stack.enter_context(patch.object(run, "prepare"))
        self.drive = stack.enter_context(patch.object(run, "drive", return_value=0))
        self.job_loop = stack.enter_context(patch.object(job, "run_job_loop", return_value=0))
        self.task = self.root / "fix-api.md"
        self.task.write_text("---\nrepo: none\n---\n# Fix the api\n\n## Done when\n```bash\ntrue\n```\n")

    def launch(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", [str(REPO / "bin/ak"), "run", *map(str, args)]), \
                redirect_stdout(out), redirect_stderr(err):
            code = AK_MAIN()
        return code, err.getvalue()

    def refused(self, *args, named):
        code, err = self.launch(*args)
        self.assertEqual(code, 2, err)
        self.assertEqual(err, f"ak run: {named}: not a seat's; ak picks the models by budget, "
                              "decides what goes first and refuses a second run of a change "
                              "under way, so launch without\n")
        self.assertEqual(list(config.RUNS.iterdir()), [])
        self.prepare.assert_not_called()
        self.drive.assert_not_called()
        self.job_loop.assert_not_called()

    def test_a_seat_names_no_model_no_place_and_no_rival(self):
        self.refused(self.task, "--exec", "opus", named="--exec")
        self.refused(self.task, "--review", "astra", named="--review")
        self.refused(self.task, "--anyway", named="--anyway")
        self.refused(self.task, "--first", "--bg", named="--first")
        self.refused(self.task, "--exec", "opus", "--review", "astra", "--first",
                     named="--exec, --review, --first")
        self.refused("--review-pr", PR, "--first", named="--first")
        self.refused("--review-pr", PR, "--review", "astra", named="--review")

    def test_outside_a_seat_the_flags_stand(self):
        opts, flags = {"--exec": "opus", "--review": None}, {"--anyway": True, "--first": False}
        self.assertEqual(run.seat_refusal(opts, flags),
                         "--exec, --anyway: not a seat's; ak picks the models by budget, decides what "
                         "goes first and refuses a second run of a change under way, so launch without")
        for seat in ("", "no-such-seat"):      # no seat, and a shell naming no recorded one
            with self.subTest(seat=seat or "none"), patch.dict(os.environ, {config.SESSION_ENV: seat}):
                self.assertIsNone(run.seat_refusal(opts, flags))
        self.assertIsNone(run.seat_refusal({"--exec": None, "--review": None}, {"--anyway": False, "--first": False}))

    def test_a_jobs_rerun_on_the_next_executor_starts_under_the_seat(self):
        # ak's own pick, relayed to the child `ak run` that spawn_bg starts under the seat's name
        children = []
        with patch.object(run, "spawn_bg", side_effect=lambda d, argv, **_kw: children.append(argv)), \
                patch.object(job, "job_await", return_value={}):
            run_dir, opts = job.job_start_task(
                config.load(), self.root, {"name": "fix-api", "task_file": str(self.task),
                                           "exec_override": "astra", "rerun_attempted": True},
                {}, lambda *_: None)
            job.job_drive(config.load(), run_dir, opts, {}, scoped=True)
        self.assertEqual(children, [[str(run_dir / "task.md"), "--exec", "astra"]])
        run.run_record.save_state(run_dir, {"state": "queued"})
        with patch.dict(os.environ, {config.RUN_DIR_ENV: str(run_dir)}):
            code, err = self.launch(*children[0])
        self.assertEqual((code, err), (0, ""))
        self.drive.assert_called_once()

if __name__ == "__main__":
    unittest.main(verbosity=2)
