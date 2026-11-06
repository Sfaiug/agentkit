"""A seat's own pull request is reviewed only on a head whose AGENTS.md answers `users:`.

The answer decides whether a reviewer holds a new feature to the project's switch, and only the
owner can give it.  The seat's launch on a head with no `users:` line is refused with the
question before it waits for a slot, a PR reviewed before as well; a head that answers is
reviewed; a launch that waited in line while its head lost the line ends blocked once its slot
frees, and no turn is spent on that head.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, from the seat of akseat.py, against the bare origin of
gitrig.py, whose main answers nothing, and the GitHub of fakegh.py, with scripted harnesses from
fakeadapter.py.  The slot is held by a run outside the seat whose executor turn waits for the
test, with ak's own knobs (max_runs, AK_HOST_READINGS, AK_SLOT_POLL) set so only the count
holds a run.
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

UNANSWERED = "---\ntests: true\nhealth: none\n---\n"
ANSWERED = "---\ntests: true\nhealth: none\nusers: none\n---\n"
READINGS = {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1,
            "slice_cpu_pressure": 0, "slice_memory_pressure": 0}


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class OwnPrUsersAnswer(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "widgets", files={"AGENTS.md": UNANSWERED})
        self.gh = GitHub(self.home)
        akconfig.write(self.home, ["opus", "astra"])
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        Seat(self.home, "acme", cwd=self.rig.path, alive=False,
             record={"workers": ["opus", "astra"]}, planned=True)
        self.asked = (f"{self.rig.path}/AGENTS.md has no users: line. Ask the owner \"Does "
                      "widgets have real users?\": \"No, straight to live\" is users: none; "
                      "\"Yes, new features stay hidden until I switch them on\" is users: real. "
                      "Add the chosen line to AGENTS.md's front matter on the PR's branch.")

    def open_pr(self, files):
        self.rig.branch("contrib", {"contrib.txt": "c\n", **files})
        return self.gh.open_pr(self.rig, "contrib")

    def push(self, rules):
        """The seat pushes a head whose AGENTS.md says `rules`."""
        self.rig.git("checkout", "-q", "contrib")
        self.rig.commit({"AGENTS.md": rules}, "rules")
        self.rig.git("checkout", "-q", "main")

    def review(self, url, *flags):
        """The seat reviews its pull request: what ak said, and the run it recorded."""
        before = set(taskfile.runs(self.home))
        done = self.home.ak("run", "--review-pr", url, "--no-merge", *flags, timeout=300,
                            env={"AGENTKIT_SESSION": "acme"}, cwd=self.rig.path)
        (run,) = set(taskfile.runs(self.home)) - before
        return done, run

    def turns(self):
        return self.fakes["claude"].n + self.fakes["codex"].n

    def assertRefused(self, done):
        self.assertEqual((done.code, done.err), (2, f"ak run: {self.asked}\n"), done.out)

    def assertReviewed(self, done):
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual([turn["role"] for turn in self.fakes["codex"].runs()], ["reviewer"])

    def test_the_seat_s_launch_on_a_head_with_no_users_line_is_refused_with_the_question(self):
        done, _ = self.review(self.open_pr({}))
        self.assertRefused(done)
        self.assertEqual(self.turns(), 0)

    def test_a_head_answering_users_none_is_reviewed(self):
        self.assertReviewed(self.review(self.open_pr({"AGENTS.md": ANSWERED}))[0])

    def test_a_launch_that_waited_while_its_head_lost_the_line_ends_blocked_unturned(self):
        del self.home.env["AK_MAX_RUNS"]
        self.home.env.update(AK_SLOT_POLL="0.5", AK_HOST_READINGS=json.dumps(READINGS))
        akconfig.write(self.home, ["opus", "astra"], settings={"max_runs": 1})
        release = self.fakes["claude"].dir / "release"
        self.addCleanup(release.touch)
        # bounded, so a turn the test never released cannot outlive it
        self.fakes["claude"].behave({**fakeadapter.WORDS["blocked"]["executor"], "sh": (
            f"for i in $(seq 900); do [ -f {shlex.quote(str(release))} ] && break; "
            "sleep 0.1; done")})
        held = self.home.ak("run", str(taskfile.write(self.home, self.rig.path, "Add retry")),
                            "--no-merge", "--bg", "--exec", "opus")
        self.assertEqual(held.code, 0, held.out + held.err)
        wait(lambda: self.fakes["claude"].n == 1, "the held run's executor turn")
        done, run = self.review(self.open_pr({"AGENTS.md": ANSWERED}), "--bg")
        self.assertEqual(done.code, 0, done.out + done.err)
        state = lambda: json.loads((run / "run.json").read_text())
        wait(lambda: state().get("slot_wait_kind") == "count", "the review queued on the count")
        self.push(UNANSWERED)
        release.touch()
        wait(lambda: state()["state"] not in ("queued", "running"), "the review's end")
        self.assertEqual((state()["state"], state()["error"]), ("blocked", self.asked))
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 0))

    def test_a_pr_reviewed_with_the_line_then_pushed_without_it_is_refused(self):
        url = self.open_pr({"AGENTS.md": ANSWERED})
        self.assertReviewed(self.review(url)[0])
        self.push(UNANSWERED)
        before = self.turns()
        self.assertRefused(self.review(url)[0])
        self.assertEqual(self.turns(), before)


if __name__ == "__main__":
    unittest.main()
