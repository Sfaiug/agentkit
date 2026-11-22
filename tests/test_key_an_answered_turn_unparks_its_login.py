"""An answered turn unparks the login it ran on: the Stop of an orchestrator seat, heard in its
harness's environment on the login the seat's record names, whose harness recorded the turn
answered, ends that login's refusals no meter showed that were made before the turn; the other
login stays parked, and whatever fails, the Stop is answered as it would have been.

Black-box: Claude Code's hooks fired in a seat's pane (tests/fixtures/hookdrive.py,
tests/fixtures/akseat.py) with no harness behind it (tests/fixtures/fakeadapter.py), over a
provider with two logins and room on every meter.  Each refusal is made by `usage.mark_exhausted`
itself in a child python3, at the moment tests/fixtures/clock.py stands it at; what is parked is
read back by `ak usage --json`.  No real login or meter is reached.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks, conversation

TESTS = Path(__file__).resolve().parent
LOGINS = ["default", "second"]
SECOND = {"AGENTKIT_ACCOUNT": "second"}     # the seat's harness, as ak launched it on that login
# A refusal of Opus on the login named that no meter showed, at the moment named.
MARK = ("import sys; sys.path[:0] = sys.argv[1:3]; from agentkit import config, usage; "
        "from fixtures.clock import Clock; usage.time = clock = Clock(None); "
        "clock.time = lambda: float(sys.argv[4]); "
        "usage.mark_exhausted(config.load(), 'anthropic', account=sys.argv[3], model='opus')")
ANSWER = {"type": "assistant", "message": {"role": "assistant", "content": [
    {"type": "text", "text": "The api is fixed and its tests pass."}]}}
REFUSED = {"type": "assistant", "isApiErrorMessage": True, "message": {
    "role": "assistant", "content": [{"type": "text", "text":
                                      "You've hit your 5-hour limit · resets 6:59pm"}]}}


@unittest.skipUnless(REAL_TMUX, "no tmux")
class AnAnsweredTurnUnparksItsLogin(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"], providers={
            "anthropic": {"mode": "subscription", "accounts": LOGINS}})
        fakeadapter.install(home, claude="pass")
        now = time.time()
        room = {"provider": "anthropic", "resets": 0, "meters": [
            {"name": "session", "used": 25, "window_secs": 18000, "resets_at": now + 10800},
            {"name": "weekly_all", "used": 25, "window_secs": 604800,
             "resets_at": now + 3 * 86400}]}
        home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {"anthropic": {
            **room, "accounts": {login: room for login in LOGINS}}}})
        self.hooks = Hooks(home)

    def mark(self, login):
        done = self.home.run(sys.executable, "-c", MARK, str(TESTS.parent), str(TESTS), login,
                             repr(time.time()))
        self.assertEqual(done.code, 0, done.err)

    def parked(self):
        """{login: whether it is parked}, as `ak usage --json` shows it."""
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        logins = json.loads(done.out)["providers"]["anthropic"]["accounts"]
        return {login: logins[login]["exhausted"] for login in LOGINS}

    def seat(self, name):
        """A seat whose record names the second login, and an open line in its plan: its Stop
        goes back, which says something."""
        return Seat(self.home, name, record={"account": "second"}, planned=True)

    def prompt(self, seat):
        fired = self.hooks.prompt("fix the api", seat, env=SECOND, finished=True)
        self.assertEqual(fired.code, 0, fired)

    def stop(self, seat, ending=ANSWER, env=SECOND):
        """The turn ends on `ending`, its Stop heard in `env`; what the hook printed."""
        path = conversation(self.home, seat)
        with path.open("a") as said:
            said.write(json.dumps(ending) + "\n")
        fired = self.hooks.fire("Stop", {"background_tasks": [], "transcript_path": str(path)},
                                seat=seat.name, pane=seat, env=env, finished=True)
        self.assertEqual(fired.code, 0, fired)
        return fired

    def answered(self, name="acme", ending=ANSWER, env=SECOND):
        """Both logins refused, then a turn of seat `name` on the second ends on `ending`, its
        Stop heard in `env`."""
        self.mark("default")
        self.mark("second")
        self.assertEqual(self.parked(), {"default": True, "second": True})
        seat = self.seat(name)
        self.prompt(seat)
        return self.stop(seat, ending, env)

    def test_the_turn_its_login_answered_unparks_that_login_alone(self):
        self.answered()
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_a_refusal_made_after_the_prompt_was_heard_stays(self):
        self.mark("default")
        seat = self.seat("acme")
        self.prompt(seat)
        self.mark("second")
        self.stop(seat)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_stop_heard_on_the_usual_login_unparks_nothing(self):
        self.answered(env={"AGENTKIT_ACCOUNT": ""})
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_turn_recorded_ending_on_a_refusal_unparks_nothing(self):
        self.answered(ending=REFUSED)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_reading_of_another_shape_leaves_the_stop_answered_as_ever(self):
        plain = self.seat("plain")
        self.prompt(plain)
        unmarked = self.stop(plain)
        self.assertTrue(unmarked.said, unmarked)
        self.mark("default")
        self.mark("second")
        snapshot = self.home.path / ".agentkit/state/usage.json"
        held = json.loads(snapshot.read_text())
        held["providers"]["anthropic"]["accounts"]["second"]["meters"] = 25
        snapshot.write_text(json.dumps(held))
        seat = self.seat("acme")
        self.prompt(seat)
        self.assertEqual(self.stop(seat).out, unmarked.out)


if __name__ == "__main__":
    unittest.main()
