"""A question scrolled out of sight is still the question its hook said, and Esc ends it.

Scrolled up from its live bottom (a wheel notch, PgUp), Claude Code 2.1.292 replaces a dialog's
key hints with a "Jump to bottom (ctrl+End) ↓" pill right above its closing rule, and the rows
left read like a composer or a draft.  Read as one, they made the hook's `asking` an answered
question, the seat `working`, and no hook fired when the view came back: the owner, scrolling the
question to read it, saw his seat say `working` for minutes.  A view the harness says is scrolled
(`[screen] away`) reads nothing, so the hook's fact stands; and an Esc, which ends a question's
turn with no Stop, ends it for an asking fact as for a working one.  The panes are real captures.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import watch

FIX = Path(__file__).resolve().parent / "fixtures"
ASKING = {"event": "Notification", "kind": "permission_prompt",
          "text": "Claude needs your permission", "at": 1000.0}


def pane(name):
    return watch.pane_tail((FIX / name).read_text(encoding="utf-8"))


def classify(name, fact=ASKING, interrupted=None):
    return watch.classify("claude", pane(name), fact, None, {}, 1100.0, interrupted=interrupted)


class ScrolledViewReadsNothing(unittest.TestCase):
    def test_a_question_scrolled_up_is_still_asking(self):
        self.assertEqual(watch.screen_state("claude", pane("claude-question-scrolled-pane.txt")),
                         (None, "", ""))
        found = classify("claude-question-scrolled-pane.txt")
        self.assertEqual((found["state"], found["authority"], found["hooked"]),
                         ("asking", "hook", "asking"))

    def test_scrolled_back_it_is_the_dialog_again(self):
        found = classify("claude-question-scrolled-back-pane.txt")
        self.assertEqual((found["state"], found["rule"]), ("asking", "Notification/permission_prompt"))

    def test_an_idle_prompt_scrolled_up_still_shows_its_composer(self):
        # the transcript scrolls; the composer under it stays live, and reads as it is
        self.assertEqual(watch.screen_state("claude", pane("claude-prompt-scrolled-pane.txt"))[:2],
                         ("at_prompt", "prompt.composer"))

    def test_the_pill_on_a_reply_row_is_read_before_the_tray(self):
        # scrolled to a reply, `● OK.` shares the pill's row, which a tray pattern takes whole
        rows = (FIX / "claude-prompt-scrolled-pane.txt").read_text(encoding="utf-8").splitlines()
        pill = next(at for at, row in enumerate(rows) if "Jump to bottom" in row)
        closing = (FIX / "claude-question-scrolled-pane.txt").read_text(
            encoding="utf-8").splitlines()[-1]
        found = watch.classify("claude", watch.pane_tail("\n".join(rows[:pill + 1] + [closing])),
                               ASKING, None, {}, 1100.0)
        self.assertEqual((found["state"], found["hooked"]), ("asking", "asking"))

    def test_a_draft_quoting_the_pill_stays_a_draft(self):
        typed = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8").replace(
            "Fix the login redirect", "Explain Jump to bottom (ctrl+End) ↓")
        rows = watch.pane_tail(typed).splitlines()
        for shown in (rows, rows[:-1]):  # under its footer, and with none drawn
            self.assertEqual(watch.screen_state("claude", "\n".join(shown))[0], "draft")

    def test_esc_on_a_question_ends_its_turn(self):
        found = classify("claude-prompt-pane.txt", interrupted=1050.0)
        self.assertEqual((found["state"], found["evidence"]),
                         ("at_prompt", "the owner interrupted its turn"))


if __name__ == "__main__":
    unittest.main()
