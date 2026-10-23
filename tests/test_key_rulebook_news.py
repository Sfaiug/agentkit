"""A seat's prompt tells it to read its current rulebook, with a code, until it says it has.

A harness reads its rulebook only when it opens, so a seat left open across a change would keep
working to rules nobody holds any more.  ak tells the seat's own conversation instead, on the
prompt that starts its next turn: the rulebook is written to the seat's `rules` file, and the
news names that file and a code.  Every prompt says it again until `ak orch rules CODE`, run in
the seat with the code that prompt gave, says the rulebook was read; then prompts say nothing.
Black-box: Claude's hooks as ak's adapter registers them, fired as Claude fires them
(tests/fixtures/hookdrive.py), and `ak orch rules` run as the seat runs it; this test fails
against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import Hooks

CONVERSATION = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"
CODE = re.compile(r"`ak orch rules ([0-9a-f]{12})`")


class RulebookNews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)

    def seat(self, name):
        """A Claude seat on its own conversation, launcher-issued, that was told nothing yet;
        returns its rules file."""
        self.home.write(f".agentkit/state/session-{name}.json",
                        {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["opus"],
                         "cwd": str(self.home.path), "conversation": CONVERSATION,
                         "id_source": "launcher", "resumable": True})
        return self.home.path / ".agentkit" / "state" / f"rules-{name}.md"

    def prompt(self, name):
        fired = self.hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": CONVERSATION},
                                seat=name)
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
        return self.home.ak("orch", "rules", code,
                            env={"AGENTKIT_SESSION": name} if name else None)

    def test_the_first_prompt_is_told_to_read_its_rulebook_and_given_a_code(self):
        rules = self.seat("acme")
        news, _ = self.told(self.prompt("acme"))
        self.assertTrue(news.startswith(f"Read {rules} in full now"), news)
        self.assertTrue(rules.read_text().strip())

    def test_every_prompt_is_told_again_with_the_same_code_until_it_is_read(self):
        self.seat("beta")
        first = self.told(self.prompt("beta"))
        for _ in range(2):
            self.assertEqual(self.told(self.prompt("beta")), first)

    def test_a_wrong_code_or_no_seat_reads_nothing_and_the_news_stands(self):
        self.seat("gamma")
        news, code = self.told(self.prompt("gamma"))
        for wrong, name in (("0123456789ab", "gamma"), (code, None), ("", "gamma")):
            with self.subTest(code=wrong, seat=name):
                done = self.read(wrong, name)
                self.assertEqual((done.code, done.out), (2, ""), done.err)
        self.assertEqual(self.told(self.prompt("gamma")), (news, code))

    def test_the_code_says_it_was_read_and_the_next_prompt_is_told_nothing(self):
        self.seat("delta")
        _, code = self.told(self.prompt("delta"))
        self.assertEqual(self.read(code, "delta"), (0, "rulebook read\n", ""))
        self.assertEqual(self.prompt("delta"), (0, "", "", []))
        # a code is spent once read: the rules it named are the seat's now
        done = self.read(code, "delta")
        self.assertEqual((done.code, done.out), (2, ""), done.err)
        self.assertEqual(self.prompt("delta"), (0, "", "", []))


if __name__ == "__main__":
    unittest.main()
