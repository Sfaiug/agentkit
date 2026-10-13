"""A run the tick launches for a seat (`run.launch_for_seat`) runs with the options its receipt
recorded: a task started again keeps its --no-merge and --rounds, a review started again its
place and reviewer. The launch sends the child no flag; the child reads its record (`run.main`),
as a resume of a run that never started does.
Offline: a temporary HOME, a fake launch and a fake loop.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, record, run

URL = "https://github.com/acme/widget/pull/7"


class SeatLaunchOptions(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def launched(self, name, opts, task=True):
        """The run directory and the argv `launch_for_seat` hands the child for `opts`."""
        directory = config.RUNS / name
        directory.mkdir()
        if task:
            (directory / "task.md").write_text("# Change a line\n")
        (directory / "log.txt").touch()
        started = []
        with patch.object(run, "preflight"), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: started.append(argv)):
            run.launch_for_seat(directory, {"launched_session": "fix-api"},
                                {"restarted": {"run": "older"}}, opts=opts, cfg=self.cfg)
        return directory, started[0]

    def driven(self, directory, argv):
        """The options the child started with `argv` drives the run with."""
        with patch.dict(os.environ, {config.RUN_DIR_ENV: str(directory)}), \
                patch.object(run.box, "check"), \
                patch.object(run, "drive", return_value=0) as drive:
            self.assertEqual(run.main(argv), 0)
        return drive.call_args.args[2]

    def test_a_task_started_again_keeps_its_recorded_options(self):
        directory, argv = self.launched("20261013-restarted-task",
                                        {"--no-merge": True, "--rounds": "1"})
        self.assertEqual(argv, [str(directory / "task.md")])       # no flag: its record has them
        recorded = record.read_state(directory)["launch_opts"]
        self.assertEqual((recorded["--no-merge"], recorded["--rounds"]), (True, "1"))
        opts = self.driven(directory, argv)
        self.assertEqual((opts["--no-merge"], opts["--rounds"]), (True, "1"))

    def test_a_review_started_again_keeps_its_place_and_reviewer(self):
        directory, argv = self.launched("20261013-restarted-review",
                                        {"--review-pr": URL, "--review": "astra", "--first": True},
                                        task=False)
        self.assertEqual(argv, ["--review-pr", URL])
        opts = self.driven(directory, argv)
        self.assertEqual((opts["--review"], opts["--first"]), ("astra", True))


if __name__ == "__main__":
    unittest.main()
