"""A queued own PR that grows past the seat limit or leaves the default branch is stopped before delivery.

Preflight checks the PR's head size and target branch at launch; a checks-only own PR that waits
for a slot while its branch grows past `orchestrator_lines` or its base branch moves off the
repository's default is refused once its slot frees, never verified or merged.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, from the seat of
akseat.py, against the bare origin of gitrig.py and the GitHub of fakegh.py, with scripted
harnesses from fakeadapter.py.
"""

import json
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

RULES = "---\ntests: test -f contrib.txt\nhealth: none\nusers: none\nreview_rounds: 0\n---\n"
READINGS = {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1,
            "slice_cpu_pressure": 0, "slice_memory_pressure": 0}


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class OwnPrChangedWhileQueued(unittest.TestCase):
    def queue_checks_only_own_pr(self):
        home = Home()
        self.addCleanup(home.close)
        del home.env["AK_MAX_RUNS"]
        home.env.update(AK_SLOT_POLL="0.5", AK_HOST_READINGS=json.dumps(READINGS))
        rig = Rig(home, "widgets", files={"AGENTS.md": RULES})
        gh = GitHub(home)
        akconfig.write(home, ["opus", "astra"],
                       settings={"max_runs": 1, "orchestrator_lines": 50})
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        Seat(home, "acme", cwd=rig.path, alive=False,
             record={"workers": ["opus", "astra"]}, planned=True)
        release = fakes["claude"].dir / "release"
        self.addCleanup(release.touch)
        # bounded, so a turn the test never released cannot outlive it
        fakes["claude"].behave({**fakeadapter.WORDS["blocked"]["executor"], "sh": (
            f"for i in $(seq 900); do [ -f {shlex.quote(str(release))} ] && break; "
            "sleep 0.1; done")})
        held = home.ak("run", str(taskfile.write(home, rig.path, "Hold slot")),
                       "--no-merge", "--bg", "--exec", "opus")
        self.assertEqual(held.code, 0, held.out + held.err)
        wait(lambda: fakes["claude"].n == 1, "the held run's executor turn")

        rig.branch("contrib", {"contrib.txt": "c\n"})
        url = gh.open_pr(rig, "contrib")
        before = set(taskfile.runs(home))
        done = home.ak("run", "--review-pr", url, "--bg", timeout=300,
                       env={"AGENTKIT_SESSION": "acme"}, cwd=rig.path)
        self.assertEqual(done.code, 0, done.out + done.err)
        (run_dir,) = set(taskfile.runs(home)) - before
        state = lambda: json.loads((run_dir / "run.json").read_text())
        wait(lambda: state().get("slot_wait_kind") == "count", "the own PR queued on the count")
        return rig, gh, fakes, run_dir, state, release

    def test_a_checks_only_own_pr_that_grows_past_the_seat_cap_while_queued_ends_blocked(self):
        rig, gh, fakes, run_dir, state, release = self.queue_checks_only_own_pr()
        rig.git("checkout", "-q", "contrib")
        rig.commit({"contrib.txt": "".join(f"line {i}\n" for i in range(100))}, "grow pr")
        rig.git("checkout", "-q", "main")
        release.touch()
        wait(lambda: state()["state"] not in ("queued", "running"), "the oversized own PR's end")
        ended = state()
        self.assertEqual((ended["state"], ended["verdict"]), ("blocked", "BLOCKED"))
        self.assertIn("too big for the seat", ended["error"])
        self.assertIsNone(gh.pr(1)["merge"])
        self.assertFalse((run_dir / "round-1/donewhen.log").exists())
        self.assertEqual((fakes["claude"].n, fakes["codex"].n), (1, 0))

    def test_a_checks_only_own_pr_retargeted_off_the_default_branch_while_queued_is_refused(self):
        rig, gh, fakes, run_dir, state, release = self.queue_checks_only_own_pr()
        rig.git("push", "-q", "origin", "main:refs/heads/staging")
        gh.edit(1, baseRefName="staging")
        release.touch()
        wait(lambda: state()["state"] not in ("queued", "running"), "the retargeted own PR's end")
        ended = state()
        self.assertEqual(ended["state"], "error")
        self.assertIn("PR #1 is based on staging, not main", ended["error"])
        self.assertIsNone(gh.pr(1)["merge"])
        self.assertFalse((run_dir / "round-1/donewhen.log").exists())
        self.assertEqual((fakes["claude"].n, fakes["codex"].n), (1, 0))


if __name__ == "__main__":
    unittest.main()
