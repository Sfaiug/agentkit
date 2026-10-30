"""A check failing on a merged commit is handed back to its seat, once per repository.

A main broken by a merge would otherwise be noticed only by the owner.  Each `ak watch` tick
reads the latest check runs of every merge commit younger than three hours and types one line
into the seat that launched the run, at its prompt:
`<check> failed on <target> after this merge: <url>. Fix the target.`, the URL the pull
request's where the check names no page of its own.  Only the newest failing merge of a
repository is told, and only once: a break already told holds back a later failing merge
there, and a later merge that passed tells nothing.  An older merge tells nothing; a seat in a
turn is told at its next prompt, however long the turn; a tick GitHub does not answer tells
nothing, and the next one does.  None of it pages the owner.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, each tick in the box `home.tick()`
builds, on projects from gitrig.py, the GitHub of fakegh.py, seats from akseat.py and the
webhook of sink.py.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, boxable, Home
from fixtures.akseat import Seat
from fixtures.fakegh import OFFLINE, GitHub
from fixtures.gitrig import Rig
from fixtures.sink import Sink


def tick(home):
    done = home.tick()
    assert done.code == 0, done.out + done.err


def told(check, repo, number):
    return (f"{check} failed on main after this merge: https://github.com/acme/{repo}/pull/"
            f"{number}. Fix the target.")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class Merges(unittest.TestCase):
    """A Home of projects, each with the seat that merged into it."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        akconfig.write(cls.home, ["opus"])
        cls.gh = GitHub(cls.home)
        cls.rigs, cls.seats = {}, {}
        cls.stage()

    @classmethod
    def merge(cls, repo, seat, number, check, conclusion, *, age=600,
              screen="claude-prompt-pane.txt"):
        """Seat `seat` merged PR `number` into `repo` `age` seconds ago, and `check` ran on
        the merge commit; the run's record."""
        if repo not in cls.rigs:
            cls.rigs[repo] = Rig(cls.home, repo)
            cls.seats[seat] = Seat(cls.home, seat, cwd=cls.rigs[repo].path, screen=screen)
        rig = cls.rigs[repo]
        sha = rig.commit({f"pr-{number}.txt": f"{number}\n"}, f"Merge {number}")
        cls.gh.check(sha, check, conclusion=conclusion)
        now, run = time.time(), f"20261020-1200-{repo}-{number}"
        return cls.home.write(f".agentkit/runs/{run}/run.json", {
            "run_id": run, "state": "pass", "verdict": "PASS", "merged": True,
            "finished_at": now - age, "started_at": now - age - 600, "repo": str(rig.path),
            "pr": f"https://github.com/acme/{repo}/pull/{number}", "merge_sha": sha,
            "launched_session": seat})

    def lines(self, seat):
        return self.seats[seat].lines()


class OncePerRepository(Merges):
    @classmethod
    def stage(cls):
        cls.merge("app", "acme", 7, "ci", "failure")
        cls.merge("api", "beta", 3, "lint", "failure", age=1200)
        cls.merge("api", "beta", 4, "build", "failure")
        cls.merge("web", "gamma", 1, "ci", "failure", age=1200)
        cls.merge("web", "gamma", 2, "ci", "success")
        cls.merge("docs", "delta", 1, "ci", "failure", age=4 * 3600)
        cls.merge("cli", "kappa", 1, "ci", "failure", screen="claude-working-pane.txt")
        tick(cls.home)
        cls.first = {name: seat.lines() for name, seat in cls.seats.items()}
        cls.merge("app", "acme", 8, "lint", "failure", age=60)
        cls.seats["kappa"].show("claude-prompt-pane.txt")
        tick(cls.home)

    def test_a_failed_check_on_the_merge_is_typed_into_the_seat_that_merged_it(self):
        self.assertEqual(self.first["acme"], [told("ci", "app", 7)])

    def test_a_told_break_holds_back_a_later_failing_merge_in_that_repository(self):
        self.assertEqual(self.lines("acme"), [told("ci", "app", 7)])

    def test_of_two_failing_merges_only_the_newer_is_told(self):
        self.assertEqual(self.lines("beta"), [told("build", "api", 4)])

    def test_a_later_merge_that_passed_tells_nothing(self):
        self.assertEqual(self.lines("gamma"), [])

    def test_a_merge_older_than_three_hours_tells_nothing(self):
        self.assertEqual(self.lines("delta"), [])

    def test_a_seat_in_a_turn_is_told_at_its_next_prompt(self):
        self.assertEqual(self.first["kappa"], [])
        self.assertEqual(self.lines("kappa"), [told("ci", "cli", 1)])

    def test_no_break_pages_the_owner(self):
        self.assertEqual([r for r in self.sink.requests if r.method == "POST"], [])


class LongTurn(Merges):
    @classmethod
    def stage(cls):
        run = cls.merge("cli", "kappa", 1, "ci", "failure", screen="claude-working-pane.txt")
        tick(cls.home)
        cls.first = cls.seats["kappa"].lines()
        # the turn outlasts the three hours a merge's checks are followed
        record = json.loads(run.read_text())
        record["finished_at"] -= 3 * 3600
        run.write_text(json.dumps(record))
        tick(cls.home)
        cls.late = cls.seats["kappa"].lines()
        cls.seats["kappa"].show("claude-prompt-pane.txt")
        tick(cls.home)
        cls.told = cls.seats["kappa"].lines()
        tick(cls.home)

    def test_a_seat_in_a_turn_is_told_nothing_while_the_turn_lasts(self):
        self.assertEqual((self.first, self.late), ([], []))

    def test_it_is_told_once_at_its_next_prompt_after_the_merge_left_the_window(self):
        self.assertEqual(self.told, [told("ci", "cli", 1)])
        self.assertEqual(self.lines("kappa"), [told("ci", "cli", 1)])


class GitHubDown(Merges):
    @classmethod
    def stage(cls):
        cls.merge("app", "acme", 7, "ci", "failure")
        cls.gh.reply("", err=OFFLINE, code=1)
        tick(cls.home)
        cls.first = cls.seats["acme"].lines()
        cls.gh.restore()
        tick(cls.home)

    def test_a_tick_github_does_not_answer_tells_nothing_and_the_next_tells_it(self):
        self.assertEqual(self.first, [])
        self.assertEqual(self.lines("acme"), [told("ci", "app", 7)])


if __name__ == "__main__":
    unittest.main()
