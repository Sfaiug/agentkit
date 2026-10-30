"""A run waiting for its slot is refused as soon as a rule it breaks lands.

On 22 Oct 2026 13 own-PR reviews were queued when the 50-line rule merged; each waited about 4
hours for a slot and was refused only then.  A launch waiting for its slot moves to the agentkit
installed when that moves, and the new code judges the launch's refusals again: a run it now
refuses ends refused at once, before any slot, and leaves the line; a run it still accepts keeps
its place and waits on, whatever GitHub answers then: a read that failed is no rule.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from
gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
The installed version is a fake git's answer for the program's own checkout, moved by the test;
the queue is held by injected host readings (AK_HOST_READINGS) against a run's peak in a history
database.  A task `from:` a branch deleted while it waits stands for the rule it now breaks;
one waits as its launch did, one as a recovered launch (`ak run resume`) does.
"""

import json
import os
from pathlib import Path
import shlex
import signal
import shutil
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akbin, akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

OLD, NEW = "aaa1111", "bbb2222"
# 3.8 of the slice's 4 G held, a run's peak 1 G: the room check holds, while the host is calm.
CALM = {"free_mb": 6000, "mem_total_mb": 16000, "cpus": 8, "load": 0.1,
        "slice_cpu_pressure": 0, "slice_memory_pressure": 0,
        "slice_memory_used_mb": 3800, "slice_memory_high_mb": 4096}
COLUMNS = ("run_id TEXT PRIMARY KEY", "repo TEXT", "executor TEXT", "reviewer TEXT",
           "rounds_used INTEGER", "final_state TEXT", "verdict TEXT", "started_at REAL",
           "finished_at REAL", "executor_seconds REAL", "done_when_seconds REAL",
           "reviewer_seconds REAL", "merge_seconds REAL", "total_seconds REAL",
           "executor_tokens INTEGER", "reviewer_tokens INTEGER", "peak_rss_mb REAL",
           "session TEXT")
# The program's version is `git -C <its checkout> rev-parse --short HEAD`; every other git is git.
GIT = """#!/bin/sh
if [ "$#" = 5 ] && [ "$1 $2" = {ask} ] && [ "$3 $4 $5" = "rev-parse --short HEAD" ]; then
    exec cat {version}
fi
exec {git} "$@"
"""


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class QueuedRunMeetsNewRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        del home.env["AK_MAX_RUNS"]
        home.env.update(AK_SLOT_POLL="0.5", AK_HOST_READINGS=json.dumps(CALM))
        cls.version = home.root / "version"
        cls.version.write_text(OLD + "\n")
        checkout = Path(akbin.AK).resolve().parents[1]
        home.fake("git", GIT.format(ask=shlex.quote(f"-C {checkout}"),
                                    version=shlex.quote(str(cls.version)),
                                    git=shlex.quote(shutil.which("git", path=":".join(akbin.SYSTEM)))))
        now = time.time()
        database = sqlite3.connect(home.path / ".agentkit" / "history.db")
        database.execute(f"CREATE TABLE runs ({', '.join(COLUMNS)})")
        database.execute("INSERT INTO runs (run_id, repo, final_state, verdict, started_at, "
                         "finished_at, peak_rss_mb) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         ("20261020-1200-fix-api", "acme", "pass", "PASS", now - 7200,
                          now - 3600, 1024))
        database.commit()
        database.close()
        cls.rig = Rig(home, "widgets")
        gh = GitHub(home)
        cls.rig.branch("contrib", {"contrib.txt": "c\n"})
        url = gh.open_pr(cls.rig, "contrib", author="other-dev")
        for branch in ("fix-api", "fix-gadget"):
            cls.rig.branch(branch, push=False)
        akconfig.write(home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(home, claude="work", codex="pass")
        cls.refused = [cls.task("Fix api", {"from": "fix-api"}),
                       cls.task("Fix gadget", {"from": "fix-gadget"})]
        cls.kept = [cls.task("Add retry", {}), cls.launch("--review-pr", url)]
        # the gadget's launcher dies; recovered, it waits as `ak run resume` from then on
        pid = cls.state(cls.refused[1])["pid"]
        os.kill(pid, signal.SIGKILL)
        wait(lambda: not Path(f"/proc/{pid}").exists()
             or Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z",
             "the gadget's launcher gone")
        done = home.ak("run", "resume", cls.refused[1].name, "--bg")
        assert done.code == 0, done.out + done.err
        wait(lambda: cls.state(cls.refused[1]).get("pid") not in (pid, None)
             and cls.refused[1].name in cls.queue(), "the gadget back in line")
        cls.before = {run: cls.state(run) for run in cls.kept}
        for branch in ("fix-api", "fix-gadget"):
            cls.rig.git("branch", "-q", "-D", branch)
        for call in ("pr view", "api"):
            gh.reply(call, err="HTTP 502: Bad Gateway\n", code=1)
        time.sleep(2)       # four polls on the same code: nothing judges it again
        cls.unjudged = [cls.state(run) for run in cls.refused]
        cls.version.write_text(NEW + "\n")
        for run in cls.refused:
            wait(lambda: cls.state(run).get("state") not in ("queued", None),
                 f"{run.name}, from a deleted branch, ended")
        wait(lambda: cls.queue() == [run.name for run in cls.kept], "the others alone in line")

    @classmethod
    def task(cls, title, front):
        return cls.launch(str(taskfile.write(cls.home, cls.rig.path, title, front=front)),
                          "--no-merge")

    @classmethod
    def launch(cls, *argv):
        before = set(taskfile.runs(cls.home))
        done = cls.home.ak("run", *argv, "--bg")
        assert done.code == 0, done.out + done.err
        (run,) = set(taskfile.runs(cls.home)) - before
        wait(lambda: cls.queue()[-1:] == [run.name], f"{run.name} in line")
        return run

    @classmethod
    def state(cls, run):
        try:
            return json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    @classmethod
    def queue(cls):
        try:
            return json.loads((cls.home.path / ".agentkit" / "runs" / ".slots.queue")
                              .read_text())["queue"]
        except (OSError, ValueError, KeyError):
            return []

    def test_a_run_the_new_code_refuses_ends_refused_before_any_slot(self):
        for run, unjudged, branch in zip(self.refused, self.unjudged, ("fix-api", "fix-gadget")):
            with self.subTest(run.name):
                self.assertEqual(unjudged.get("state"), "queued")
                state = self.state(run)
                self.assertEqual(state["state"], "error")
                self.assertTrue(state["error"].endswith(f": from: {branch!r} is not a local branch"),
                                state["error"])
                self.assertTrue((run / "result.md").is_file())
                self.assertNotIn("slot_started_at", state)
                self.assertNotIn("worktree", state)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))

    def test_a_run_the_new_code_accepts_keeps_its_place_whatever_github_answers(self):
        time.sleep(2)       # four polls on the new code: still waiting, as it was
        for run in self.kept:
            with self.subTest(run.name):
                before, state = self.before[run], self.state(run)
                self.assertEqual(state["state"], "queued")
                self.assertEqual((state["queued_at"], state["pid"]),
                                 (before["queued_at"], before["pid"]))
        self.assertEqual(self.queue(), [run.name for run in self.kept])


if __name__ == "__main__":
    unittest.main()
