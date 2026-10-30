"""A routine line starts a seat's turn only when it ends that seat's wait; otherwise it rides.

A merge, or a merged change going live, a repair's included, is news a seat owing work only
acts on when its turn ended waiting on it: its `ak wait` names that run, or nothing else of the
seat's holds the turn.  Any other is typed into no seat and wakes none: it rides on the seat's
next prompt, beside every other line waiting there, oldest first, once, where the seat's harness
hands a prompt context at all; on one that does not (Grok) it is typed as before.  A change going
live before its merge is told is typed after that merge, in one line.  A failed or blocked ending is
the seat's to decide, and is typed whatever it waits on.  Black-box: the program `AK_BIN` names runs
`ak wait` and `ak watch` from outside (tests/fixtures/akbin.py), Claude's hooks as its adapter
registers them (hookdrive.py), seats of akseat.py, one asleep with a harness of fakeadapter.py
that would wake it, on a project from gitrig.py and the GitHub of fakegh.py.
"""

import json
import re
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.hookdrive import Hooks

PR = "https://github.com/acme/app/pull/7"
HELD = "20261029-0800-fix-db"     # no seat's run, going: its line holds it until the lander ends it
RIDES = "Runs you have not been told about yet:\n"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class Routine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "grok"])
        cls.fake = fakeadapter.install(home, claude="pass")["claude"]
        cls.hooks = Hooks(home)
        cls.rig = Rig(home, "app", files={"AGENTS.md": "---\nhealth: true\n---\n"})
        cls.sha = cls.rig.head()
        GitHub(home).check(cls.sha, "ci")
        home.write(f".agentkit/runs/{HELD}/run.json", {
            "run_id": HELD, "title": "fix-db", "state": "waiting",
            "waiting_on": {"line": "acme/app"}})
        cls.seat = Seat(home, "acme", cwd=cls.rig.path, planned=True)
        cls.seats = {"acme": cls.seat}
        cls.stage()
        for _ in range(3):
            done = home.tick()
            assert done.code == 0, done.out + done.err
            # a line typed into every seat, and all of acme's taken
            if len(cls.seat.lines()) >= cls.typed and all(
                    seat.typed() for seat in cls.seats.values()):
                break

    @classmethod
    def wait(cls, name, on):
        done = cls.home.ak("wait", on, env={"AGENTKIT_SESSION": name})
        assert done.code == 0, done.out + done.err

    @classmethod
    def ended(cls, run, ago, seat="acme", **record):
        now = time.time()
        cls.home.write(f".agentkit/runs/{run}/run.json", {
            "run_id": run, "title": run[14:], "state": "pass", "verdict": "PASS",
            "merged": True, "finished_at": now - ago, "started_at": now - ago - 600,
            "repo": str(cls.rig.path), "launched_session": seat, **record})

    @classmethod
    def proven(cls, run, ago, **record):
        """Merged `ago` seconds ago, with the `health:` this tick finds passing."""
        cls.ended(run, ago, pr=PR, merge_sha=cls.sha, health={"command": "true"}, **record)

    def prompt(self):
        """The run lines the owner's next prompt in acme carries, else None."""
        fired = self.hooks.fire("UserPromptSubmit",
                                {"prompt": "go on", "session_id": "conv-acme"})
        self.assertEqual(fired.code, 0, fired.err)
        context = "".join(answer["hookSpecificOutput"]["additionalContext"]
                          for answer in fired.said)
        found = re.search(re.escape(RIDES) + r"((?:run .*\n?)+)", context)
        return found and found.group(1).splitlines()

    def told_merge_then_live_in_one_line(self):
        lines = self.seat.wait_lines(1)
        self.assertEqual(len(lines), 1, lines)
        merge, live = lines[0].split(" Decide the next step. ")
        self.assertTrue(merge.startswith(f"run {self.RUN} finished "), lines)
        self.assertEqual(live, f"run {self.RUN} is live: {PR}.", lines)
        self.assertIsNone(self.prompt())


class Rides(Routine):
    """acme waits on HELD and owes work; two merges of its own and two changes going live, a
    repair's one of them, are not what it waits on, a failed and a blocked run are its to decide;
    beta, asleep, and delta, on Grok, wait on HELD too, and a merge of each one's own ends."""
    OLD, NEW = "20261029-0930-old-merge", "20261029-0900-new-merge"
    REPAIR = "20261029-0905-fix-target"
    FAILED, BLOCKED = "20261029-0901-fix-ui", "20261029-0902-fix-cli"
    typed = 2

    @classmethod
    def stage(cls):
        cls.wait("acme", HELD)
        cls.seats["delta"] = Seat(cls.home, "delta", model="grok", screen="grok-prompt-pane.txt",
                                  planned=True)
        cls.wait("delta", HELD)
        cls.ended("20261029-0904-delta-merge", 300, seat="delta")
        cls.beta = Seat(cls.home, "beta", alive=False, planned=True,
                        record={"launched": 1, "asleep": 2})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(cls.beta.cwd))
        cls.home.write(f".claude/projects/{folder}/conv-beta.jsonl",
                       '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        cls.fake.answer("interactive", shlex.join([sys.executable, str(PANE), str(
            cls.beta.screen_file), str(cls.beta.typed_file)]), given=("conv-beta",))
        cls.wait("beta", HELD)
        cls.ended("20261029-0903-beta-merge", 300, seat="beta")
        cls.ended(cls.OLD, 900)
        cls.proven(cls.NEW, 600)
        cls.proven(cls.REPAIR, 500, repair="github.com/acme/app")
        cls.ended(cls.FAILED, 400, state="fail", verdict="FAIL", merged=False)
        cls.ended(cls.BLOCKED, 350, state="blocked", verdict="BLOCKED", merged=False)

    def test_a_failed_and_a_blocked_ending_are_typed_and_no_merge_is(self):
        lines = self.seat.wait_lines(2)
        self.assertEqual(sorted(line.split(" finished ")[0] for line in lines),
                         [f"run {self.FAILED}", f"run {self.BLOCKED}"], lines)

    def test_a_merge_is_typed_where_the_harness_takes_no_prompt_context(self):
        typed = self.seats["delta"].typed()
        self.assertTrue(typed.startswith("run 20261029-0904-delta-merge finished "), typed)

    def test_a_sleeping_seat_s_merge_wakes_it_not(self):
        sessions = self.home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        self.assertNotIn("beta", sessions)
        self.assertEqual(self.fake.calls("interactive"), [])

    def test_the_merges_and_the_live_changes_ride_the_next_prompt_oldest_first_once(self):
        self.seat.wait_lines(2)
        for run in (self.NEW, self.REPAIR):
            record = json.loads((self.home.path / f".agentkit/runs/{run}/run.json").read_text())
            self.assertIn("live_at", record)
        lines = self.prompt()
        # the repair's merge is recorded, never typed; both changes went live on one tick
        self.assertEqual([line.split(":")[0].split(" finished ")[0] for line in lines or []],
                         [f"run {self.OLD}", f"run {self.NEW}", f"run {self.NEW} is live",
                          f"run {self.REPAIR} is live"], lines)
        self.assertIsNone(self.prompt())


class EndsTheWait(Routine):
    """acme waits on its own run, which merges and goes live on one tick: one line ends its
    wait."""
    RUN = "20261029-0910-fix-api"
    typed = 1

    @classmethod
    def stage(cls):
        cls.home.write(f".agentkit/runs/{cls.RUN}/run.json", {
            "run_id": cls.RUN, "title": "fix-api", "state": "waiting",
            "waiting_on": {"line": "acme/app"}, "launched_session": "acme"})
        cls.wait("acme", cls.RUN)
        cls.proven(cls.RUN, 30)

    def test_its_merge_and_its_going_live_are_typed_in_one_line(self):
        self.told_merge_then_live_in_one_line()



class CarriesItsMerge(Routine):
    """acme owes work and waits only on its own run's change going live: the merge rides, and
    the change going live ends that wait, so the one line typed then carries the merge first."""
    RUN = "20261029-0920-fix-auth"
    typed = 1

    @classmethod
    def stage(cls):
        cls.proven(cls.RUN, 30)

    def test_its_going_live_is_typed_after_its_merge_in_one_line(self):
        self.told_merge_then_live_in_one_line()


if __name__ == "__main__":
    unittest.main()
