"""Claude seats disable session feedback on launch and dismiss a survey already on screen."""

import re
import shlex
import unittest

from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks, conversation

DISABLED = "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1"
QUESTION = "How is Claude doing this session? (optional)"
OPTIONS = "  1: Bad    2: Fine   3: Good   {unsure}0: Dismiss"
INK = "\x1b[38;5;153m"
EFFORT = "                                      ● high · /effort\n"
BOX = "\n──────────────────────────────────── acme ─\n❯ {draft}\n───────────────────────────────────────────"
FOOTER = "\n  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents"


def survey(unsure=False):
    keys = OPTIONS.format(unsure="4: Unsure " if unsure else "")
    tinted = re.sub(r"\d(?=:)", lambda m: INK + m[0] + "\x1b[39m", keys)
    return f"{INK}●\x1b[39m \x1b[1m{QUESTION}\x1b[0m\n{tinted}"


class ClaudeFeedbackSurvey(unittest.TestCase):
    def test_interactive_launch_disables_feedback(self):
        with Home() as home:
            book = home.write("rulebook-acme.md", "Finish acme.")
            done = home.run(REPO / "adapters/claude.sh", "interactive", "opus", "high",
                            env={"AGENTKIT_RULEBOOK": str(book)})
            self.assertEqual(done.code, 0, done.err)
            self.assertIn(DISABLED, shlex.split(done.out))

    def test_fresh_and_resumed_seat_commands_disable_feedback(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            fresh = home.ak("orch", "acme", "--model", "opus", "--workers", "opus", "--dry-run")
            self.assertEqual(fresh.code, 0, fresh.err)
            words = shlex.split(fresh.out.splitlines()[-1])
            self.assertIn(DISABLED, words)
            session_id = words[words.index("--session-id") + 1]
            seat = Seat(home, "acme", alive=False, record={"conversation": session_id})
            home.write(conversation(home, seat),
                       '{"type":"user","message":{"role":"user","content":"go"}}\n')
            resumed = home.ak("orch", "acme", "--dry-run")
            self.assertEqual(resumed.code, 0, resumed.err)
            words = shlex.split(resumed.out.splitlines()[-1])
            self.assertEqual(words[words.index("--resume") + 1], session_id)
            self.assertIn(DISABLED, words)

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_only_a_survey_at_the_bottom_gets_the_dismiss_key(self):
        plain = f"  {QUESTION}\n" + OPTIONS.format(unsure="")
        empty = BOX.format(draft="") + FOOTER
        cases = (
            ("survey", survey() + empty, "0"),
            ("unsure", survey(unsure=True) + empty, "0"),
            ("plain survey below effort", EFFORT + plain + empty, "0"),
            ("bottom row", plain, "0"),
            ("quote above effort", plain + "\n" + EFFORT + empty, ""),
            ("quote next to empty composer", plain + empty, ""),
            ("coloured quote in transcript", survey() + "\n  End of quote." + empty, ""),
            ("draft", survey() + BOX.format(draft="finish acme") + FOOTER, ""),
        )
        for label, screen, keys in cases:
            with self.subTest(label), Home() as home:
                seat = Seat(home, "acme", screen=screen)
                fired = Hooks(home).fire("Notification", {"notification_type": "idle_prompt"},
                                         pane=seat, finished=True)
                self.assertEqual(fired.code, 0, fired.err)
                self.assertEqual(seat.typed(), keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
