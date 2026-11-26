"""A job launched from a seat saved with no reviewers lands each task on its checks, with no reviewer,
and a task whose builder is spent waits for that builder alone, with no run.

Black-box against AK_BIN, fakeadapter's failing reviewer and a bare GitHub origin, on a project
whose review_rounds is 3 so only the seat's empty reviewers list turns review off.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

FAILING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fake defect", "it matters", "--run", "false"], ["done"]]}


class AJobsTaskWithNoReviewer(unittest.TestCase):
    def staged(self):
        """Tasks a and b from seat acme, saved with no reviewers: opus builds, and any review fails."""
        home = Home()
        self.addCleanup(home.close)
        home.env.update(AK_NOTIFY_SINK=None,
                        AK_HOST_READINGS=json.dumps({"cpus": 4, "load": 0, "free_mb": 16000}))
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                       settings={"review_rounds": 3})
        rules = "---\ntests: true\nhealth: none\nusers: none\nreview_rounds: 3\n---\n# Widgets\n"
        rig = Rig(home, "widgets", files={"AGENTS.md": rules})
        rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        GitHub(home).grant(rig.slug, "WRITE")
        # a adds a.txt and retry.txt; opus's second turn builds b, rewriting retry.txt, and were it
        # a's review it would find that file a defect of a's change and fail a
        fakes = fakeadapter.install(home, codex=FAILING, claude=[
            {**fakeadapter.WORK, "write": {"a.txt": "a\n", "retry.txt": "draft\n"}}, "fail"])
        checks = ("test -f a.txt", "grep -qx hello retry.txt")
        Seat(home, "acme", model="opus", cwd=rig.path, alive=False, planned=checks,
             record={"workers": ["opus"], "reviewers": []})
        tasks = [str(taskfile.write(home, rig.path, f"Add {name}", name=name, done_when=(check,)))
                 for name, check in zip("ab", checks)]
        return home, rig, fakes, (*tasks, "--in-order")

    def test_an_ordered_job_from_a_seat_with_no_reviewer_merges_without_a_reviewer_turn(self):
        home, rig, fakes, args = self.staged()
        # in the foreground the launch is the job's loop, and it exits as the job ends
        done = home.ak("run", *args, timeout=600, env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.out + done.err)
        # without review off the seat's builder, opus, reviews each task in a turn of its own
        self.assertEqual([turn["role"] for turn in fakes["claude"].runs()], ["executor"] * 2)
        self.assertEqual(fakes["codex"].n, 0)
        states = [json.loads((run_dir / "run.json").read_text()) for run_dir in taskfile.runs(home)]
        self.assertEqual([(state["verdict"], state["merged"], state.get("reviewers"),
                           state["reviewer"]) for state in states], [("PASS", True, [], None)] * 2)
        self.assertEqual([rig.origin("show", f"main:{name}") for name in ("a.txt", "retry.txt")],
                         ["a", "hello"])

    def test_its_task_waits_for_its_executor_alone(self):
        home, _, fakes, args = self.staged()
        fakes["claude"].answer("usage", json.dumps({"meters": [{"name": "weekly", "used": 100}]}))
        proc = home.spawn("run", *args, env={"AGENTKIT_SESSION": "acme"})
        deadline, task = time.monotonic() + 90, {}
        while (proc.poll() is None and time.monotonic() < deadline and not taskfile.runs(home)
               and not task.get("budget_wait")):
            receipts = list((home.path / ".agentkit/jobs").glob("*/job.json"))
            task = json.loads(receipts[0].read_text())["tasks"][0] if receipts else {}
            time.sleep(.05)
        self.assertTrue(task.get("budget_wait"), home.log("spawn-1.err").read_text())
        self.assertEqual(taskfile.runs(home), [])


if __name__ == "__main__":
    unittest.main()
