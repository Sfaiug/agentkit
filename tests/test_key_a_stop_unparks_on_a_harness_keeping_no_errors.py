"""A Stop unparks its login on a harness that keeps no record of errors: a Grok Build seat's Stop,
heard on the login its record names and handing over the model's last words, ends that login's
refusals no meter showed that were made before the turn; the other login stays parked, and a
StopFailure, a Stop with an error `terminationReason`, or one heard on the usual login unparks
nothing.

The Home, its seat, its refusals and its hooks are tests/fixtures/unparking.py's.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.unparking import Unparking

WORDS = "The api is fixed and its tests pass."


class AStopUnparksOnAHarnessKeepingNoErrors(Unparking):
    HARNESS, PROVIDER, MODEL, SCREEN = "grokbuild", "xai", "grok", "grok-prompt-pane.txt"

    def began(self, name="acme"):
        """Both logins refused, then a prompt of seat `name` heard on the second."""
        self.mark("default")
        self.mark("second")
        self.assertEqual(self.parked(), {"default": True, "second": True})
        seat = self.seat(name)
        self.prompt(seat)
        return seat

    def test_its_stop_unparks_that_login_alone(self):
        seat = self.began()
        self.stop(seat, lastAssistantMessage=WORDS)
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_its_stop_failure_unparks_nothing(self):
        seat = self.began()
        self.stop(seat, event="StopFailure", error="rate_limit", lastAssistantMessage=WORDS)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_stop_ending_on_an_error_unparks_nothing(self):
        seat = self.began()
        self.stop(seat, lastAssistantMessage=WORDS, terminationReason="ERROR")
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_stop_heard_on_the_usual_login_unparks_nothing(self):
        seat = self.began()
        self.stop(seat, env={"AGENTKIT_ACCOUNT": ""}, lastAssistantMessage=WORDS)
        self.assertEqual(self.parked(), {"default": True, "second": True})


if __name__ == "__main__":
    unittest.main()
