"""A seat that read its rulebook is told again when it changes or a compaction drops it, and
only a seat's own conversation, on a harness whose prompt hook takes context, is told at all.

The rulebook is ak's rules with the host's `rules.md` after them, so the owner adding a rule
reaches a seat left open only through the news its next prompt carries: what changed, as a
diff, with a new code.  A compaction leaves the conversation holding only the rules it was
opened with, so its next prompt tells it the rulebook again; a resume keeps what it read.  A
client started inside the seat inherits its name and is not it, a worker runs the same harness
with the same hooks, and a harness that reads no prompt context could never act on news, so
each of them is told nothing.  Black-box: each harness's hooks as ak's adapter for it registers
them, fired as that harness fires them (tests/fixtures/hookdrive.py), and `ak orch rules` run
as the seat runs it; this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import Hooks, adapter

CONVERSATION = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"
CODE = re.compile(r"`ak orch rules ([0-9a-f]{12})`")
SILENT = (0, "", "", [])


class RulebookRetold(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)
        cls.state = cls.home.path / ".agentkit" / "state"

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
        """The news a prompt carried as Claude reads it, and the code in it."""
        self.assertEqual(len(fired.said), 1, fired.out)
        output = fired.said[0]["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        news = output["additionalContext"]
        found = CODE.search(news)
        self.assertIsNotNone(found, news)
        return news, found.group(1)

    def read(self, code, name):
        return self.home.ak("orch", "rules", code, env={"AGENTKIT_SESSION": name})

    def read_once_told(self, name):
        """The seat told its rulebook and saying it read it; returns the code it was given."""
        _, code = self.told(self.prompt(name))
        self.assertEqual(self.read(code, name), (0, "rulebook read\n", ""))
        self.assertEqual(self.prompt(name), SILENT)
        return code

    def test_a_changed_rulebook_is_told_as_what_changed_with_a_new_code(self):
        self.seat("acme")
        first = self.read_once_told("acme")
        self.home.write(".agentkit/rules.md", "Always say hello.\n")
        news, code = self.told(self.prompt("acme"))
        change, rules = self.state / "change-acme.md", self.state / "rules-acme.md"
        self.assertTrue(news.startswith(f"Your rulebook changed: read {change} now"), news)
        self.assertIn(str(rules), news)
        self.assertNotEqual(code, first)
        self.assertIn("Always say hello.", change.read_text())
        self.assertIn("Always say hello.", rules.read_text())
        self.assertEqual(self.read(code, "acme"), (0, "rulebook read\n", ""))
        self.assertEqual(self.prompt("acme"), SILENT)

    def test_a_code_given_before_the_rules_changed_reads_nothing(self):
        self.seat("beta")
        _, stale = self.told(self.prompt("beta"))
        self.home.write(".agentkit/rules.md", "Be brief.\n")
        done = self.read(stale, "beta")
        self.assertEqual((done.code, done.out), (2, ""), done.err)
        _, code = self.told(self.prompt("beta"))
        self.assertNotEqual(code, stale)
        self.assertEqual(self.read(code, "beta"), (0, "rulebook read\n", ""))

    def test_after_a_compaction_the_next_prompt_is_told_the_rulebook_again(self):
        self.seat("gamma")
        self.read_once_told("gamma")
        compacted = self.hooks.fire("SessionStart",
                                    {"source": "compact", "session_id": CONVERSATION},
                                    seat="gamma")
        self.assertEqual(compacted, SILENT)
        news, _ = self.told(self.prompt("gamma"))
        self.assertTrue(news.startswith(f"Read {self.state / 'rules-gamma.md'} in full now"),
                        news)

    def test_a_resume_or_another_conversations_compaction_leaves_what_it_read(self):
        self.seat("parser")
        self.read_once_told("parser")
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
