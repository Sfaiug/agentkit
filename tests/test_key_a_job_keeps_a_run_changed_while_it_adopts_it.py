"""A relaunched job keeps its member run when another process changes that run while the job
adopts it, and starts no second run of the task.

On 9 Nov a job relaunched after ak moved home adopted its interrupted member run while the
tick's resume rung was resuming it.  The job's resume was refused for the record changing under
it, the record's state read as before, and the job started the task over: two runs of one task.
Here `ak run resume <job>` relaunches a dead job holding an interrupted run, and while the job's
resume waits for the slot lock this test holds, the test stamps that run's record, its state
left as it was.  Black-box: records written by hand where ak keeps them, and the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from fixtures.akbin import Home, owner

RUN, JOB = "20261109-0900-add-retry-file", "20261109-090000-acme"


def wait(seen, home, what, bound=120):
    deadline = time.monotonic() + bound
    while not (found := seen()):
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}: " + home.log("spawn-1.err").read_text())
        time.sleep(.05)
    return found


def waited_on(lock):
    """Whether a process waits for the flock this test holds on `lock`."""
    inode = f":{lock.stat().st_ino} "
    return any("->" in line and inode in line
               for line in Path("/proc/locks").read_text().splitlines())


class JobKeepsARunChangedWhileItAdoptsIt(unittest.TestCase):
    def test_the_job_keeps_its_run_and_starts_no_second_one(self):
        home = Home()
        self.addCleanup(home.close)
        task = taskfile.write(home, "none")
        # the identity of a launcher since gone, as a job's is after its host moved
        gone = subprocess.Popen(["sleep", "60"])
        launched = owner(gone.pid)
        gone.kill()
        gone.wait()
        runs = home.path / ".agentkit/runs"
        home.write(f".agentkit/runs/{RUN}/task.md", task.read_text())
        home.write(f".agentkit/runs/{RUN}/log.txt", "")
        kept = home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "Add retry file", "state": "interrupted", "verdict": None,
            "pid": None, "launched_session": None, "started_at": time.time() - 600,
            "error": "Run process exited or its identity changed."})
        receipt = home.write(f".agentkit/jobs/{JOB}/job.json", {
            "job_id": JOB, "seat": None, "started_at": time.time() - 600, "finished_at": None,
            "parallel": None, "opts": {}, **launched,
            "tasks": [{"name": "add-retry-file.md", "title": "Add retry file",
                       "state": "running", "run_id": RUN, "task_file": str(task)}]})
        with (runs / ".slots.lock").open("a") as slots:
            fcntl.flock(slots, fcntl.LOCK_EX)
            home.spawn("run", "resume", JOB)
            wait(lambda: waited_on(runs / ".slots.lock"), home, "waited for the slot lock")
            # the tick's rung stamps its order on the run before its own resume takes it
            stamped = {**json.loads(kept.read_text()),
                       "resume_notice": {"at": time.time(), "role": "executor",
                                         "restarted": False}}
            kept.with_name("stamped.json").write_text(json.dumps(stamped))
            os.replace(kept.with_name("stamped.json"), kept)

        def decided():
            entry, = json.loads(receipt.read_text())["tasks"]
            return entry if entry.get("retry_after") or entry.get("run_id") != RUN or \
                entry["state"] not in ("running", "queued") else None

        entry = wait(decided, home, "decided on its run")
        self.assertEqual(entry["run_id"], RUN, entry)
        self.assertEqual(sorted(path.name for path in runs.iterdir() if path.is_dir()), [RUN])


if __name__ == "__main__":
    unittest.main()
