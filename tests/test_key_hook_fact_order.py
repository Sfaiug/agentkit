"""A seat's fact is the newest event its hooks heard, and an idle prompt never ends a wait.

A seat's row reads its word from the fact its hooks keep (`hook-<seat>.json`).  A harness runs
some hooks without waiting on them, so an event can finish after a newer one; whichever hook
writes it, it never lands over a fact heard later, or a seat would read `working` after its turn
ended, or at its prompt mid-turn.  Claude says its prompt is idle a minute after a turn ends even
while background work the turn started is in flight: the Stop that handed that work over stands,
so the seat still reads as working on it, while a question going up replaces it as ever.
Black-box: Claude's hooks as ak's adapter registers them, fired as Claude fires them
(tests/fixtures/hookdrive.py); this test fails against `/bin/false`.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import Hooks, transcript

PROMPT = {"prompt": "go", "session_id": "x"}
# Claude Code hands its Stop the work still in flight; a sub-agent is work the seat waits on.
WORK = [{"id": "b1", "type": "subagent", "status": "running", "description": "Slow check"}]
QUESTION = {"tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which colour?"}]}}


class Seats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)

    def seat(self, name):
        self.home.write(f".agentkit/state/session-{name}.json",
                        {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["opus"]})
        return name

    def fact(self, name):
        path = self.home.path / ".agentkit" / "state" / f"hook-{name}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def fire(self, event, payload, seat):
        fired = self.hooks.fire(event, {"hook_event_name": event, **payload}, seat=seat)
        self.assertEqual(fired.code, 0, fired.err)
        return self.fact(seat)

    def stop(self, seat, work):
        said = transcript(self.home, f"{seat}-{len(work)}", "Running.")
        return self.fire("Stop", {"transcript_path": said, "background_tasks": work}, seat)


class NewerFact(Seats):
    def test_no_event_lands_over_a_fact_heard_later_and_each_lands_over_an_older_one(self):
        said = transcript(self.home, "older", "Running.")
        events = {"a prompt": ("UserPromptSubmit", PROMPT),
                  "a permission notice": ("Notification", {
                      "notification_type": "permission_prompt",
                      "message": "Claude needs your permission"}),
                  "a Stop on background work": ("Stop", {"transcript_path": said,
                                                          "background_tasks": WORK}),
                  "a Stop": ("Stop", {"transcript_path": said, "background_tasks": []}),
                  "a question": ("PermissionRequest", QUESTION)}
        for case, (event, payload) in events.items():
            with self.subTest(case):
                name = self.seat("acme")
                self.home.write(f".agentkit/state/stop-{name}.json",
                                {"session": name, "turn": time.time() - 30, "blocks": 0})
                # heard an hour from now: what any hook hears now is older
                later = {"session": name, "event": "Stop", "kind": "", "text": "",
                         "at": time.time() + 3600}
                self.home.write(f".agentkit/state/hook-{name}.json", later)
                self.assertEqual(self.fire(event, payload, name), later)
                older = {**later, "event": "PostCompact", "kind": "manual",
                         "at": time.time() - 60}
                self.home.write(f".agentkit/state/hook-{name}.json", older)
                fact = self.fire(event, payload, name)
                self.assertEqual(fact["event"], event, fact)
                self.assertGreater(fact["at"], older["at"])


class IdlePrompt(Seats):
    def test_an_idle_prompt_leaves_standing_the_stop_that_handed_over_background_work(self):
        name = self.seat("beta")
        self.fire("UserPromptSubmit", PROMPT, name)
        stopped = self.stop(name, WORK)
        self.assertEqual((stopped["event"], stopped["kind"]), ("Stop", "background"))
        idle = {"notification_type": "idle_prompt", "message": "Claude is waiting for your input"}
        self.assertEqual(self.fire("Notification", idle, name), stopped)

    def test_a_question_going_up_still_replaces_that_stop(self):
        name = self.seat("gamma")
        self.fire("UserPromptSubmit", PROMPT, name)
        stopped = self.stop(name, WORK)
        self.assertEqual((stopped["event"], stopped["kind"]), ("Stop", "background"))
        fact = self.fire("PermissionRequest", QUESTION, name)
        self.assertEqual((fact["event"], fact["kind"], fact["text"]),
                         ("PermissionRequest", "AskUserQuestion", "Which colour?"))
        self.assertGreater(fact["at"], stopped["at"])



if __name__ == "__main__":
    unittest.main()
