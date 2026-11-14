"""A seat stays open until the owner closes it, whatever its rest and whatever memory reads (the
owner, 9 Nov 2026): one whose turn ended two hours ago is still open after a tick with memory
tight, and after one with memory free.  One an older ak put to sleep (its record marked asleep since its launch, gone from tmux,
its conversation kept) is open again on its own conversation after the next tick, and a run's
ending owed to it is typed at its next quiet prompt.  Black-box: `AK_BIN` runs each tick from
outside, in the box `home.tick()` builds (tests/fixtures/akbin.py), over seats of akseat.py,
Claude's hooks as its adapter registers them (hookdrive.py) and the harness of fakeadapter.py."""

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
from fixtures.hookdrive import Hooks

TIGHT = {"mem_total_mb": 16000, "cpus": 8, "load": 0.1, "free_mb": 100}
FREE = {**TIGHT, "free_mb": 15000}
RUN = "20261109-0900-fix-api"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class RestingSeatStaysOpen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        del home.env["AK_MAX_RUNS"]       # its host gates on: memory is read as injected
        akconfig.write(home, ["opus"])
        cls.fake = fakeadapter.install(home, claude="pass")["claude"]
        cls.resting = Seat(home, "acme")
        cls.slept = Seat(home, "beta", alive=False, record={"launched": 1, "asleep": 2})
        for seat in (cls.resting, cls.slept):
            # a conversation Claude filed under the seat's path, which the seat resumes
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/conv-{seat.name}.jsonl",
                       '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        # reopened, the harness shows the seat's screen again and keeps what is typed in
        argv = [sys.executable, str(PANE), str(cls.slept.screen_file), str(cls.slept.typed_file)]
        cls.fake.answer("interactive", shlex.join(argv), given=("conv-beta",))
        hooks = Hooks(home)
        hooks.fire("UserPromptSubmit", {"prompt": "go"}, pane=cls.resting)
        hooks.fire("Stop", {"background_tasks": [], "transcript_path": "",
                            "last_assistant_message": "Done."}, pane=cls.resting, finished=True)
        fact = home.path / ".agentkit/state/hook-acme.json"
        home.write(fact, {**json.loads(fact.read_text()), "at": time.time() - 7200})
        cls.tick()
        cls.open = home.tmux("list-sessions", "-F", "#{session_name}").out.split()

    @classmethod
    def tick(cls, readings=TIGHT):
        done = cls.home.tick(env={"AK_HOST_READINGS": json.dumps(readings)})
        assert done.code == 0, done.out + done.err

    def test_a_seat_at_rest_two_hours_with_memory_tight_stays_open(self):
        self.assertIn("acme", self.open)

    def test_a_seat_at_rest_two_hours_with_memory_fine_stays_open(self):
        self.tick(FREE)
        self.assertIn("acme", self.home.tmux("list-sessions", "-F", "#{session_name}").out.split())

    def test_a_seat_put_to_sleep_is_open_again_and_takes_its_run_s_ending(self):
        self.assertIn("beta", self.open)
        self.assertEqual(["conv-beta" in call["argv"] for call in self.fake.calls("interactive")],
                         [True])
        now = time.time()
        self.home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "fix the api", "launched_session": "beta", "state": "fail",
            "verdict": "FAIL", "started_at": now - 600, "finished_at": now})
        for _ in range(3):      # a harness not yet at its prompt is typed it by the next tick
            self.tick()
            if self.slept.lines():
                break
        line, = self.slept.wait_lines(1)
        self.assertIn(RUN, line)


if __name__ == "__main__":
    unittest.main()
