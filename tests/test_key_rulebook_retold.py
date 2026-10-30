"""A seat handed its rulebook holds it until it changes or a compaction drops it, and only a
seat's own conversation, on a harness whose prompt hook takes context, is told at all.

A resume keeps what the conversation was handed.  A client started inside the seat inherits its
name and is not it, a worker runs the same harness with the same hooks, and a harness that reads
no prompt context could never act on news, so each of them is told nothing.  What each prompt
carries is tests/test_key_rulebook_news.py's.  Black-box: each harness's hooks as ak's adapter
for it registers them, fired as that harness fires them (tests/fixtures/hookdrive.py); this test
fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import Hooks, adapter, read_rules

CONVERSATION = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"
SILENT = (0, "", "", [])


class RulebookRetold(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)

    def seat(self, name, model="opus"):
        """A seat on its own conversation, launcher-issued, that was told nothing yet."""
        self.home.write(f".agentkit/state/session-{name}.json",
                        {"orchestrator": model, "workers": [model], "reviewers": [model],
                         "cwd": str(self.home.path), "conversation": CONVERSATION,
                         "id_source": "launcher", "resumable": True})

    def payload(self, conversation=CONVERSATION):
        return {"prompt": "go", "session_id": conversation}

    def prompt(self, name, conversation=CONVERSATION, env=None):
        fired = self.hooks.fire("UserPromptSubmit", self.payload(conversation), seat=name,
                                env=env)
        self.assertEqual(fired.code, 0, fired.err)
        return fired

    def told(self, fired):
        """The news a prompt carried, as Claude reads it."""
        self.assertEqual(len(fired.said), 1, fired.out)
        self.assertEqual(fired.said[0]["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def handed(self, name):
        """The seat's first prompt names its whole rulebook, which it reads, and the next
        carries nothing."""
        self.told(self.prompt(name))
        read_rules(self.home, name)
        self.assertEqual(self.prompt(name), SILENT)

    def test_a_resume_or_another_conversations_compaction_leaves_what_it_was_handed(self):
        self.seat("parser")
        self.handed("parser")
        for source, conversation in (("resume", CONVERSATION), ("compact", "other")):
            with self.subTest(source=source, conversation=conversation):
                started = self.hooks.fire("SessionStart", {"source": source,
                                                           "session_id": conversation},
                                          seat="parser")
                self.assertEqual(started, SILENT)
                self.assertEqual(self.prompt("parser"), SILENT)

    def test_only_the_seats_own_conversation_is_told(self):
        self.seat("delta")
        for case, name, conversation, env in (
                ("another conversation in the seat", "delta", "other", None),
                ("no seat", None, CONVERSATION, None),
                ("a worker", "delta", CONVERSATION, {"AK_RUN_ROLE": "worker"})):
            with self.subTest(case):
                self.assertEqual(self.prompt(name, conversation, env), SILENT)
        self.told(self.prompt("delta"))

    def test_a_harness_whose_prompt_hook_takes_no_context_is_told_nothing(self):
        self.seat("fix-api", model="grok")
        fired = Hooks(self.home, "grokbuild").fire("UserPromptSubmit", self.payload(),
                                                   seat="fix-api")
        self.assertEqual(fired, SILENT)
        # Muse registers no prompt hook: its one hook verb is what a prompt would reach
        self.seat("beta-ui", model="spark")
        fired = adapter(self.home, "muse", "hook", seat="beta-ui",
                        payload={"hook_event_name": "UserPromptSubmit", **self.payload()})
        self.assertEqual(fired, SILENT)


if __name__ == "__main__":
    unittest.main()
