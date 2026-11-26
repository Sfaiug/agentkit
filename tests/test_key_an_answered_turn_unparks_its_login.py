"""An answered turn unparks the login it ran on: the Stop of an orchestrator seat, heard in its
harness's environment on the login the seat's record names, whose harness recorded the turn
answered, ends that login's refusals no meter showed that were made before the turn; the other
login stays parked, and whatever fails, the Stop is answered as it would have been.

The Home, its seat and its refusals are tests/fixtures/unparking.py's.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.unparking import SECOND, Unparking

ANSWER = {"type": "assistant", "message": {"role": "assistant", "content": [
    {"type": "text", "text": "The api is fixed and its tests pass."}]}}
REFUSED = {"type": "assistant", "isApiErrorMessage": True, "message": {
    "role": "assistant", "content": [{"type": "text", "text":
                                      "You've hit your 5-hour limit · resets 6:59pm"}]}}


class AnAnsweredTurnUnparksItsLogin(Unparking):
    def answered(self, name="acme", ending=ANSWER, env=SECOND):
        """Both logins refused, then a turn of seat `name` on the second ends on `ending`, its
        Stop heard in `env`."""
        self.mark("default")
        self.mark("second")
        self.assertEqual(self.parked(), {"default": True, "second": True})
        seat = self.seat(name)
        self.prompt(seat)
        return self.stop(seat, ending, env=env)

    def test_the_turn_its_login_answered_unparks_that_login_alone(self):
        self.answered()
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_a_refusal_made_after_the_prompt_was_heard_stays(self):
        self.mark("default")
        seat = self.seat("acme")
        self.prompt(seat)
        self.mark("second")
        self.stop(seat, ANSWER)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_refusal_made_without_a_model_goes_as_one_of_the_turns_model(self):
        self.mark("default", model="")
        self.mark("second", model="")
        self.assertEqual(self.parked(), {"default": True, "second": True})
        seat = self.seat("acme")
        self.prompt(seat)
        self.stop(seat, ANSWER)
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_a_stop_heard_on_the_usual_login_unparks_nothing(self):
        self.answered(env={"AGENTKIT_ACCOUNT": ""})
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_turn_recorded_ending_on_a_refusal_unparks_nothing(self):
        self.answered(ending=REFUSED)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_reading_of_another_shape_leaves_the_stop_answered_as_ever(self):
        plain = self.seat("plain")
        self.prompt(plain)
        unmarked = self.stop(plain, ANSWER)
        self.assertTrue(unmarked.said, unmarked)
        self.mark("default")
        self.mark("second")
        snapshot = self.home.path / ".agentkit/state/usage.json"
        held = json.loads(snapshot.read_text())
        held["providers"]["anthropic"]["accounts"]["second"]["meters"] = 25
        snapshot.write_text(json.dumps(held))
        seat = self.seat("acme")
        self.prompt(seat)
        self.assertEqual(self.stop(seat, ANSWER).out, unmarked.out)


if __name__ == "__main__":
    unittest.main()
