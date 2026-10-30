"""A seat the owner reopens after its harness ended goes on with what the end cut off.

On 30 Oct 2026 a seat's harness died an hour into a background workflow, and nothing reopened
it: tmux could not fork its pane-died hook.  The owner opened it with its number, and it came
back on its conversation told nothing, its workflow lost, silent at its prompt.  The owner's own
reopen -- the menu's number and `ak orch NAME` alike -- now tells it what the end cut off, as
ak's own reopens do; a seat the owner stopped ended on purpose and comes back told nothing, not
even a line an earlier reopen still owed it.
Black-box: the program `AK_BIN` names runs `ak orch` from outside through tests/fixtures/akbin.py,
beside seats of tests/fixtures/akseat.py whose hooks are fired as Claude fires them
(tests/fixtures/hookdrive.py), each reopened by a scripted harness of fakeadapter.py.
"""

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
from fixtures.hookdrive import Hooks

WORKFLOW = {"id": "w1", "type": "workflow", "status": "running", "description": "audit acme"}
# Each seat's hooks as Claude fired them before its harness ended.
FIRED = {"workflow": [("UserPromptSubmit", {"prompt": "go"}),
                      ("Stop", {"background_tasks": [WORKFLOW], "transcript_path": "",
                                "last_assistant_message": "Started it."})],
         "turn": [("UserPromptSubmit", {"prompt": "go"})],
         "stopped": [("UserPromptSubmit", {"prompt": "go"})]}


def conversation(n):
    return f"7c2d1e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5{n}"


def dead(home, name):
    return home.tmux("display-message", "-p", "-t", f"={name}:", "#{pane_dead}").out.strip()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OwnerReopensAnEndedSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        fake = fakeadapter.install(home, claude="pass")["claude"]
        hooks, cls.seats = Hooks(home), {}
        for n, (name, fired) in enumerate(FIRED.items()):
            seat = cls.seats[name] = Seat(home, name, record={"conversation": conversation(n)})
            # Claude files a workspace's conversations under its path, each character that is
            # not a letter or a digit a dash: this one it has opened, so it is resumed.
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/{conversation(n)}.jsonl",
                       '{"type":"user","message":{"role":"user","content":"hello"}}\n')
            fake.answer("interactive", shlex.join([sys.executable, str(PANE),
                                                   str(seat.screen_file), str(seat.typed_file)]),
                        given=(conversation(n),))
            for event, payload in fired:
                done = hooks.fire(event, payload, seat=name, pane=seat)
                assert done.code == 0, done
        # Both harnesses end with no pane-died hook to reopen them, and the third is stopped.
        for name in ("workflow", "turn"):
            done = home.tmux("respawn-pane", "-k", "-t", f"={name}:", "true")
            assert done.code == 0, done.err
            deadline = time.monotonic() + 30
            while dead(home, name) != "1":
                assert time.monotonic() < deadline, f"{name}'s pane never died"
                time.sleep(0.05)
        stopped = home.ak("orch", "stop", "stopped")
        assert stopped.code == 0, stopped.out + stopped.err
        cls.reopened = {name: home.ak("orch", name, tty=True) for name in FIRED}
        cls.first = {call["argv"][-1]: call["env"].get("AGENTKIT_FIRST_PROMPT")
                     for call in fake.calls("interactive")}

    def test_ak_orch_reopens_each(self):
        for n, (name, done) in enumerate(self.reopened.items()):
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertIn(conversation(n), self.first, name)

    def test_a_seat_that_held_a_workflow_is_told_it_held_it(self):
        self.assertIn("background work: workflow", self.first[conversation(0)] or "")

    def test_a_seat_cut_off_mid_turn_is_told_its_turn_was_cut_off(self):
        self.assertIn("in the middle of a turn", self.first[conversation(1)] or "")

    def test_a_seat_the_owner_stopped_comes_back_told_nothing(self):
        self.assertFalse(self.first.get(conversation(2), "never reopened"))


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class OwnerStopsAReopenedSeat(unittest.TestCase):
    def test_the_line_its_reopen_still_owed_goes_with_the_stop(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            fake = fakeadapter.install(home, claude="pass")["claude"]
            # a conversation its harness never opened: each reopen is fresh, its line owed to
            # the tick, and stopped before any tick typed it
            seat = Seat(home, "acme")
            fake.answer("interactive", shlex.join([sys.executable, str(PANE),
                                                   str(seat.screen_file), str(seat.typed_file)]))
            fired = Hooks(home).fire("UserPromptSubmit", {"prompt": "go"}, seat="acme", pane=seat)
            self.assertEqual(fired.code, 0, fired)
            self.assertEqual(home.tmux("kill-session", "-t", "=acme").code, 0)
            for argv in (("orch", "acme"), ("orch", "stop", "acme"), ("orch", "acme")):
                done = home.ak(*argv, tty=True)
                self.assertEqual(done.code, 0, done.out + done.err)
            seat.pane = home.tmux("display-message", "-p", "-t", "=acme:", "#{pane_id}").out.strip()
            seat._settle()      # at its prompt: a line still owed would go in at this tick
            ticked = home.tick()
            self.assertEqual(ticked.code, 0, ticked.out + ticked.err)
            self.assertEqual(seat.lines(), [])


if __name__ == "__main__":
    unittest.main()
