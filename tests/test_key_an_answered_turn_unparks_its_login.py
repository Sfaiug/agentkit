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
from fixtures import akconfig
from fixtures.unparking import LOGINS, SECOND, Unparking

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

    def test_a_refusal_no_meter_can_hold_unparks_only_on_its_model(self):
        akconfig.write(self.home, {"opus": "claude", "other": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": LOGINS}})
        snapshot = self.home.path / ".agentkit/state/usage.json"
        held = json.loads(snapshot.read_text())
        provider = held["providers"]["anthropic"]
        for record in (provider, *provider["accounts"].values()):
            record["meters"] = []
            record["none"] = True
        snapshot.write_text(json.dumps(held))
        self.mark("default")
        self.mark("second")
        self.assertEqual(self.parked(), {"default": True, "second": True})
        seat = self.seat("acme")
        self.prompt(seat)
        self.stop(seat, ANSWER)
        self.assertEqual(self.parked(), {"default": True, "second": False})
        self.mark("second", model="other")
        self.assertEqual(self.parked(), {"default": True, "second": True})
        self.prompt(seat)
        self.stop(seat, ANSWER)
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


class GrokBuildAnsweredTurnUnparksItsLogin(Unparking):
    """Grok Build keeps its turns' errors in updates.jsonl, so its Stop unparks as Claude's does."""

    HARNESS, PROVIDER, MODEL, SCREEN = "grokbuild", "xai", "grok", "grok-prompt-pane.txt"
    WORDS = "The api is fixed and its tests pass."

    def completed(self, seat, stop_reason="end_turn", **extra):
        return {"timestamp": 1795726461, "method": "_x.ai/session/update", "params": {
            "sessionId": seat.record["conversation"],
            "update": {"sessionUpdate": "turn_completed", "stop_reason": stop_reason, **extra}}}

    def began(self, name="acme"):
        self.mark("default")
        self.mark("second")
        self.assertEqual(self.parked(), {"default": True, "second": True})
        seat = self.seat(name)
        self.prompt(seat)
        return seat

    def test_the_turn_its_login_answered_unparks_that_login_alone(self):
        seat = self.began()
        self.stop(seat, self.completed(seat), lastAssistantMessage=self.WORDS)
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_a_turn_recorded_ending_on_an_error_unparks_nothing(self):
        seat = self.began()
        self.stop(seat, self.completed(seat, stop_reason="error",
                                       agent_result="API error (status 402 Payment Required): "
                                                    "usage_limit_reached"),
                  lastAssistantMessage=self.WORDS)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_its_stop_failure_unparks_nothing(self):
        seat = self.began()
        self.stop(seat, event="StopFailure", error="rate_limit", lastAssistantMessage=self.WORDS)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_stop_without_a_record_unparks_nothing(self):
        seat = self.began()
        self.updates(seat).unlink()
        self.stop(seat, lastAssistantMessage=self.WORDS)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_stop_heard_on_the_usual_login_unparks_nothing(self):
        seat = self.began()
        self.stop(seat, self.completed(seat), env={"AGENTKIT_ACCOUNT": ""},
                  lastAssistantMessage=self.WORDS)
        self.assertEqual(self.parked(), {"default": True, "second": True})


if __name__ == "__main__":
    unittest.main()
