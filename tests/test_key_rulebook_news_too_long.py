"""A rulebook change too long for a seat's prompt reaches it as a file it acknowledges.

Claude Code hands its model a prompt hook's context longer than 10,000 UTF-16 code units only
as a file and that file's first 2,000 characters.  A change that would make the context longer
is written to the seat's `change` file instead, ending with `ak orch rules CODE`, and the prompt
carries a pointer to it.  Nothing is held until that command runs: every prompt points again,
with the same code while the rules stay the same, however little else it carries, and after it
prompts carry nothing.  An open question rides an owner's prompt and counts toward the limit;
where it leaves no room for anything naming the file it goes alone, and the next prompt points.  A
change that fits is still carried inline and held at hand-over.  Black-box: Claude's hooks as ak's
adapter registers them, fired as Claude fires them (tests/fixtures/hookdrive.py); this test
fails against `/bin/false`.
"""

import hashlib
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home
from fixtures.hookdrive import Hooks

CONVERSATION = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"
SHIPPED = Path(AK).resolve().parents[1] / "orchestrator.md"   # ak's own rules, beside it
CHANGE = ".agentkit/state/change-acme.md"
LIMIT = 10000
SILENT = (0, "", "", [])
QUESTION = "Which schema should the parser read?"
NOT_OWNER = "<task-notification>done"      # a turn begun on finished work: no question rides
# Each one character, two UTF-16 code units and four UTF-8 bytes: only a count in code units
# takes 5,000 of them past the limit and leaves 4,000 within it.
WIDE = "\N{GRINNING FACE}"


def units(text):
    return len(text.encode("utf-16-le")) // 2


def diff(rule):
    """How the diff from the launch's rules shows `rule` taking Rule one's place."""
    return "\n-Rule one.\n" + "".join(f"+{line}" for line in rule.splitlines(True))


class TooLong(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.hooks = Hooks(self.home)
        self.rules("Rule one.\n")
        launched = f"{SHIPPED.read_text().rstrip()}\n\nRule one.\n"
        self.home.write(".agentkit/state/rulebook-acme.md", launched)
        self.home.write(".agentkit/state/session-acme.json",
                        {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["opus"],
                         "cwd": str(self.home.path), "conversation": CONVERSATION,
                         "id_source": "launcher", "resumable": True,
                         "rulebook_sha": hashlib.sha256(launched.encode()).hexdigest()})

    def rules(self, own):
        self.home.write(".agentkit/rules.md", own)

    def ask(self, question):
        done = self.home.ak("notify", "needs", question, "--session", "acme",
                            env={"AK_NOTIFY_SINK": "off"})
        self.assertEqual(done.code, 0, done.err)

    def prompt(self, words="go"):
        fired = self.hooks.fire("UserPromptSubmit", {"prompt": words, "session_id": CONVERSATION},
                                seat="acme")
        self.assertEqual(fired.code, 0, fired.err)
        return fired

    def told(self, words="go"):
        """What the next prompt carries, as Claude reads it."""
        fired = self.prompt(words)
        self.assertEqual(len(fired.said), 1, fired.out)
        news = fired.said[0]["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(units(news), LIMIT)
        return news

    def pointed(self, words="go"):
        """The pointer the next prompt carries, and the code its file ends with."""
        news = self.told(words)
        self.assertIn(str(self.home.path / CHANGE), news)
        written = (self.home.path / CHANGE).read_text()
        code = re.fullmatch(r"ak orch rules (\S+)", written.rstrip("\n").rsplit("\n", 1)[-1])
        self.assertTrue(code, written[-200:])
        self.assertNotIn(code[1], news)
        return news, written, code[1]

    def test_a_change_too_long_is_pointed_to_and_written_whole_to_a_file_ending_with_the_command(self):
        for rule in ("Rule two.\n" + "Say it again.\n" * 1800, f"Rule two. {WIDE * 5000}\n"):
            with self.subTest(units=units(rule)):
                self.rules(rule)
                news, written, _ = self.pointed()
                self.assertNotIn("Rule two.", news)
                self.assertIn(diff(rule), written)

    def test_the_pointer_comes_again_with_the_same_code_until_the_code_comes_back(self):
        self.rules(f"Rule two. {WIDE * 5000}\n")
        news, written, code = self.pointed()
        self.assertEqual(self.pointed(), (news, written, code))
        done = self.home.ak("orch", "rules", code, env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.prompt(), SILENT)

    def test_a_file_named_beside_a_question_is_named_again_on_a_prompt_with_room_to_spare(self):
        self.rules(f"Rule two. {WIDE * 4000}\n")          # within the limit alone
        self.ask(f"{QUESTION} {'Q' * 2000}")
        news, _, code = self.pointed()
        self.assertIn(QUESTION, news)
        news, _, again = self.pointed(NOT_OWNER)
        self.assertEqual((again, QUESTION in news), (code, False))

    def test_a_question_that_leaves_no_room_to_name_the_file_goes_alone(self):
        self.rules(f"Rule two. {WIDE * 5000}\n")
        # its context, as tests/test_key_answer_context.py pins it, 12 units short of the limit
        self.ask(f"{QUESTION} {'Q' * 9860}")
        news = self.told()
        self.assertIn(QUESTION, news)
        self.assertNotIn(str(self.home.path / CHANGE), news)
        self.pointed(NOT_OWNER)

    def test_a_change_within_the_limit_is_carried_inline_and_held_at_hand_over(self):
        rule = f"Rule two. {WIDE * 4000}\n"
        self.rules(rule)
        news = self.told()
        self.assertIn(diff(rule), news)
        self.assertNotIn("ak orch rules", news)
        self.assertEqual(self.prompt(), SILENT)


if __name__ == "__main__":
    unittest.main()
