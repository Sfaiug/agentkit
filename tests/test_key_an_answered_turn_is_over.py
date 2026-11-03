"""An answered worker goes to checks and review; a refused worker resumes its work.

Black-box through AK_BIN, with an invented repository and scripted harnesses.
"""

import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, rerun_boxed
from fixtures.gitrig import Rig
from test_key_exhausted_resume import wait_for
from test_key_silent_worker import NO_CLOSING


class AnsweredTurnIsOver(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "widgets")
        akconfig.write(self.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        self.fakes = fakeadapter.install(self.home, claude=NO_CLOSING, codex="pass")
        self.task = taskfile.write(self.home, self.rig.path)

    def launch(self):
        return self.home.ak("run", str(self.task), "--no-merge", timeout=300)

    def passed(self, done):
        self.assertEqual(done.code, 0, done.out + done.err)
        self.directory = taskfile.only_run(self.home)
        state = json.loads((self.directory / "run.json").read_text())
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        self.assertEqual([row["verdict"] for row in state["round_summaries"]], ["PASS"])
        self.assertTrue(state["round_summaries"][0]["done_when"])
        self.assertEqual(self.fakes["codex"].n, 1)

    def test_committed_work_without_a_closing_is_reviewed_after_one_executor_call(self):
        self.passed(self.launch())
        self.assertEqual(self.fakes["claude"].n, 1)
        self.assertIn("wrote retry.txt", (self.directory / "result.md").read_text())

    def test_done_with_a_detached_sleep_stops_it_without_another_executor_call(self):
        marker = f"AK_ANSWERED_SLEEP={self.home.root}".encode()
        self.fakes["claude"].behave({**fakeadapter.WORK, "sh":
            f"AK_ANSWERED_SLEEP={shlex.quote(str(self.home.root))} setsid sleep 600 & child=$!; "
            'while [ "$(cat /proc/$child/comm)" != sleep ]; do sleep .01; done'})
        self.passed(self.launch())
        self.assertEqual(self.fakes["claude"].n, 1)
        self.assertIn("sleep 600", (self.directory / "log.txt").read_text())
        for process in Path("/proc").iterdir():
            if process.name.isdigit():
                try:
                    self.assertNotIn(marker, (process / "environ").read_bytes().split(b"\0"))
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    pass

    def test_after_a_spent_window_resets_the_worker_gets_a_continuation(self):
        self.fakes["claude"].behave(
            {"final": "You have hit your usage limit. Try again at {in 10}.", "exit": 1},
            "work")
        refused = self.launch()
        self.assertEqual(refused.code, 1, refused.out + refused.err)
        directory = taskfile.only_run(self.home)
        state = json.loads((directory / "run.json").read_text())
        self.assertEqual(state["state"], "exhausted")
        reset = time.time() + 11
        wait_for(lambda: time.time() > reset, "usage window reset", bound=60)
        self.passed(self.home.ak("run", "resume", directory.name, timeout=300))
        calls = self.fakes["claude"].runs()
        self.assertEqual(len(calls), 2)
        prompt = Path(calls[1]["argv"][3]).read_text()
        self.assertIn("Continue this turn and finish it", prompt)
        self.assertEqual(calls[1]["argv"][5:], ["sid-claude-1"])


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
