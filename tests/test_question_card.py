"""Every yes-or-no question reads as one calm card, `terminal.confirm`: a blank line, the question,
one dim line on what the answer means, `✓ Keep` highlighted then `✗ <answer>` in the warn colour,
and a blank line.  Esc keeps; Enter or a click answers.  On the main screen and in the popup it
opens under the seat's row, the rows below moving down, and on a phone no choice wraps.

The card is read in-process with the keys faked, and drawn on the real menu in a child on a pty
of its own through tests/test_close_and_info.py's Menu, in a throwaway HOME with the seats and the
stop faked.  Nothing here starts a seat or signals any process but the test's own child.
"""

import copy
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import test_close_and_info
from test_close_and_info import ESC, Menu
from agentkit import menu, run, stop, terminal
from agentkit import record

Key = terminal.Key
QUESTION = "Stop fix-api and everything it runs?"
MEANS = "2 runs stop with it; ak cannot reopen the session: Stop removes its record."
NONE = "No runs stop with it; ak cannot reopen the session: Stop removes its record."  # no runs
# The child's count of a seat's runs, slow: the card is up before it lands.
SLOW = """
import time
def session_runs(name):
    time.sleep(1.5)
    return ["one", "two", "three"]
menu.session_runs = session_runs
"""
CFG = {"defaults": {"orchestrator": "opus", "workers": ["opus"]},
       "providers": {"anthropic": {"mode": "subscription"}, "openai": {"mode": "subscription"}},
       "models": {"opus": {"harness": "claude", "model": "claude-opus-5", "effort": "xhigh",
                           "provider": "anthropic"},
                  "astra": {"harness": "codex", "model": "gpt-7", "effort": "xhigh",
                            "provider": "openai"}}}


def ask(keys, cols=120):
    """(the answer, the card's lines, what the choices wrote) for `keys` pressed on the card,
    its first line on row 5."""
    shown = {}

    def around(card):
        shown["card"] = card
        return 5
    with patch.object(terminal, "read_key", side_effect=keys), \
            patch.object(terminal, "width", return_value=cols), \
            patch.object(terminal, "colour_depth", return_value=256), \
            patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}), \
            redirect_stdout(io.StringIO()) as out:
        answer = terminal.confirm(QUESTION, MEANS, "Stop", around)
    return answer, shown["card"], out.getvalue()


class QuestionCard(unittest.TestCase):
    def test_the_card_is_the_question_what_it_means_and_keep_first(self):
        _, card, out = ask([Key("esc")])
        with patch.object(terminal, "colour_depth", return_value=256):
            dim, warn = terminal.styled("  " + MEANS, "dim"), terminal.styled("✗ Stop", "amber")
        self.assertEqual(card, ["", "  " + QUESTION, dim, "", "", ""])
        # the choices on the card's two rows before its last: Keep lit, Stop in the warn colour
        keep, stop = out.removeprefix("\x1b[8;1H\r").split("\x1b[K\n\r")[:2]
        self.assertEqual(terminal.ANSI.sub("", keep), "› ✓ Keep")
        self.assertEqual(stop.removesuffix("\x1b[K\n"), "  " + warn)
        # on a phone the question and its meaning wrap and no choice does
        _, card, out = ask([Key("esc")], cols=40)
        self.assertEqual([terminal.ANSI.sub("", line) for line in card],
                         ["", "  Stop fix-api and everything it runs?",
                          "  2 runs stop with it; ak cannot reopen",
                          "  the session: Stop removes its record.",
                          "", "", ""])
        self.assertIn("\x1b[9;1H\r", out)

    def test_esc_keeps_and_enter_on_the_second_choice_answers(self):
        self.assertFalse(ask([Key("esc")])[0])
        self.assertFalse(ask([Key("enter")])[0])                    # Enter on Keep keeps too
        self.assertTrue(ask([Key("down"), Key("enter")])[0])
        self.assertTrue(ask([Key("click", col=4, row=9)])[0])      # a click on `✗ Stop`
        self.assertFalse(ask([Key("click", col=4, row=2)])[0])     # ... and anywhere else keeps

    def test_the_stop_card_opens_under_its_row_at_120_and_40_columns(self):
        for cols in (120, 40):
            with self.subTest(cols=cols):
                shown = Menu(self, {"alpha": "working", "beta": "working"}, cols=cols)
                shown.frame()
                mark = shown.mark()
                shown.send(b"x")
                asked = shown.frame(keys="esc back", after=mark)
                top, answers = shown.choices(after=mark)
                card = ["", *(f"  {line}" for text in (menu.STOP_ASK.format("alpha"), NONE)
                              for line in terminal.wrap(text, min(cols, 120) - 2)), "", "", ""]
                first = top - len(card) + 2           # its first line's index on the screen
                self.assertEqual(asked[first:first + len(card)], card)
                self.assertIn("alpha", asked[first - 1])            # right under its row
                self.assertIn("beta", asked[first + len(card)])     # the row below, moved down
                self.assertEqual(answers, ["› ✓ Keep", "  ✗ Stop"])
                for line in asked:
                    self.assertLessEqual(terminal.cells(line), cols, line)
                mark = shown.mark()
                shown.send(ESC)
                lines = shown.frame(after=mark)
                self.assertNotIn(menu.STOP_ASK.format("alpha"), lines)
                shown.leave()
                self.assertNotIn("<stopped", shown.text())

    def test_the_card_is_up_before_its_runs_are_counted(self):
        with patch.object(test_close_and_info, "CHILD", test_close_and_info.CHILD.replace(
                "orch.cmd_stop = cmd_stop\n", "orch.cmd_stop = cmd_stop\n" + SLOW)):
            shown = Menu(self, {"alpha": "working"}, rows=24, cols=40)
        shown.frame()
        mark, pressed = shown.mark(), time.monotonic()
        shown.send(b"x")
        top, _ = shown.choices(after=mark)
        self.assertLess(time.monotonic() - pressed, 1.0)     # the count takes 1.5 s
        asked = shown.frame(keys="esc back", after=mark)
        self.assertEqual(asked[top - 4:top - 1], ["  Its runs stop with it; ak cannot",
                                                  "  reopen the session: Stop removes its",
                                                  "  record."])
        # down on Keep; the count lands one line shorter, moving `✗ Stop` onto that row; up there
        shown.send(f"\x1b[<0;4;{top}M".encode())
        counted = shown.frame(lambda lines: "  3 runs stop with it; ak cannot reopen" in lines,
                              keys="esc back", after=mark)
        self.assertEqual(counted.index("  the session: Stop removes its record.") + 3, top)
        shown.send(f"\x1b[<0;4;{top}m".encode())             # no click: the card is still up
        time.sleep(0.3)
        self.assertNotIn("<stopped", shown.text())
        mark = shown.mark()
        shown.send(ESC)
        shown.frame(after=mark)
        shown.leave()
        self.assertNotIn("<stopped", shown.text())

    def test_the_count_is_the_runs_a_stop_stops(self):
        # what stop.cmd_stop takes: a run not ended, and an `error` still waiting on its owner
        states = {"going": {"state": "running"}, "queued": {"state": "queued"},
                  "acknowledged": {"state": "interrupted", "recovery_acknowledged_at": 1},
                  "retried": {"state": "error", "recovery_pending": True},
                  "errored": {"state": "error"},
                  "failed": {"state": "fail", "recovery_pending": True},
                  "passed": {"state": "pass"}, "elsewhere": {"state": "running", "seat": "tidy"}}
        with patch.object(record, "run_dirs", return_value=[Path(name) for name in states]), \
                patch.object(record, "read_state", side_effect=lambda path: states[path.name]), \
                patch.object(run, "launched_session",
                             side_effect=lambda state: state.get("seat", "fix-api")):
            counted = [path.name for path in menu.session_runs("fix-api")]
        self.assertEqual(counted, ["going", "queued", "acknowledged", "retried"])
        self.assertEqual([menu.stop_means(runs) for runs in (None, 0, 1, 4)], [
            f"{start} with it; ak cannot reopen the session: Stop removes its record." for start in
            ("Its runs stop", "No runs stop", "1 run stops", "4 runs stop")])

    def test_every_caller_asks_on_the_one_card(self):
        # the popup's own seat, asked under its own row
        shown = Menu(self, {"alpha": "working", "omega": "working"}, own="omega")
        shown.frame()
        mark = shown.mark()
        shown.send(b"x")
        asked = shown.frame(keys="esc back", after=mark)
        self.assertIn("  " + menu.STOP_ASK.format("omega"), asked)
        self.assertIn("  " + NONE, asked)
        self.assertEqual(shown.choices(after=mark)[1], ["› ✓ Keep", "  ✗ Stop"])
        mark = shown.mark()
        shown.send(ESC)
        shown.frame(after=mark)
        shown.leave()
        self.assertNotIn("<stopped", shown.text())
        # removing a model, a provider and a subscription: each hands the card to its screen
        seen = []

        def confirm(question, meaning, answer, around, wait=None):
            drawn = io.StringIO()
            with redirect_stdout(drawn):
                row = around(["<card>"])
            seen.append((question, meaning, answer, drawn.getvalue().split("\n")[row - 1]))
            return False
        cfg = copy.deepcopy(CFG)
        cfg["providers"]["anthropic"]["accounts"] = ["default", "b2"]
        with patch.object(terminal, "confirm", side_effect=confirm), \
                patch.object(terminal, "read_key",
                             side_effect=[Key("down"), Key("down"), Key("enter"), Key("esc")]), \
                patch.object(terminal, "choose", side_effect=["ChatGPT", "Claude II"]), \
                redirect_stdout(io.StringIO()):
            menu.config_model(cfg, "opus")
            self.assertEqual(menu.config_remove_provider(cfg), "")
            self.assertEqual(menu.config_remove_provider(cfg), "")
        self.assertEqual(seen, [
            ("Remove opus from the config?", menu.REMOVE_ASK[1], "Remove", "<card>"),
            ("Remove ChatGPT and its models?", menu.REMOVE_PROVIDER_ASK[1], "Remove", "<card>"),
            ("Remove Claude II?", menu.REMOVE_SUBSCRIPTION_ASK[1], "Remove", "<card>")])
        self.assertEqual(cfg["providers"]["anthropic"]["accounts"], ["default", "b2"])
        self.assertEqual(set(cfg["models"]), {"opus", "astra"})
        # and no screen draws a Keep of its own
        self.assertNotIn('"Keep"', Path(menu.__file__).read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
