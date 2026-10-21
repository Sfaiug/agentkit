"""An Antigravity seat runs under the seat wrapper, and reads as what agy 1.3.5 is doing.

Each screen is a real agy 1.3.5 capture under tests/fixtures/ (see its README), replayed
through watch.screen_state and watch.classify.  Every one of them read `working` before: an
idle seat on a model whose label has brackets of its own, one narrower than its footer's model,
one with a command agy moved to the background, its permission and question dialogs, and the
footer one Ctrl-C draws.  The terms page of a first run keeps that footer and is no prompt.
"""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import watch  # noqa: E402

FIX = REPO / "tests/fixtures"


def pane(name):
    return (FIX / f"antigravity-{name}-pane.txt").read_text(encoding="utf-8")


def read(name):
    """(screen_state's state and rule, classify's state and rule) of that capture."""
    tail = watch.pane_tail(pane(name))
    found = watch.classify("antigravity", tail, None, None, {}, 10000.0)
    return watch.screen_state("antigravity", tail)[:2], (found["state"], found["rule"])


class AntigravitySeatStates(unittest.TestCase):

    def test_each_screen_reads_as_what_agy_is_doing(self):
        for name, reading in (
                # `agentkit (GPT-OSS 120B (Medium))  /agents`
                ("bracketed-label", ("at_prompt", "prompt.composer")),
                # 40 columns: `? for shortcuts` alone
                ("narrow", ("at_prompt", "prompt.composer")),
                # `... /agents · 1 task(s) · /tasks`, the command listed under the composer
                ("background", ("at_prompt", "prompt.composer")),
                ("background-draft", ("draft", "draft.typed")),
                # both over an `esc to cancel` footer
                ("permission", ("asking", "asking.permission")),
                ("question", ("asking", "asking.question")),
                ("ctrl-c", ("at_prompt", "prompt.composer"))):
            with self.subTest(name):
                self.assertEqual(read(name), (reading, reading))

    def test_a_taller_dialog_still_reads_asking(self):
        # more choices, or a longer command, push its heading up; its hint stays on the footer
        for name, short, tall in (
                ("question", "  3. Write-in...",
                 "  3. Green\n  4. Yellow\n  5. Orange\n  6. Write-in..."),
                ("permission", "   touch perm2.txt",
                 "   cat <<'EOF' >acme.txt\n   one\n   two\n   three\n   four\n   EOF")):
            with self.subTest(name):
                self.assertEqual(pane(name).count(short), 1)
                tail = watch.pane_tail(pane(name).replace(short, tall))
                self.assertEqual(watch.screen_state("antigravity", tail)[:2],
                                 ("asking", f"asking.{name}"))

    def test_a_dialog_s_words_typed_or_said_open_no_dialog(self):
        # agy draws a dialog's header from the left edge, where a draft (`> `) and a reply
        # (indented) never start
        said = "Requesting permission for: 4. No, cancel Question 1/1: enter Select · esc Skip"
        for name, words, reading in (
                ("background-draft", "draft while task runs", ("draft", "draft.typed")),
                ("ctrl-c", "promised.", ("at_prompt", "prompt.composer"))):
            with self.subTest(name):
                tail = watch.pane_tail(pane(name).replace(words, said))
                self.assertEqual(watch.screen_state("antigravity", tail)[:2], reading)

    def test_a_terms_page_under_the_ctrl_c_footer_is_no_prompt(self):
        self.assertEqual(read("terms-ctrl-c")[0], (None, ""))

    def test_the_usage_panel_over_an_empty_composer_is_no_draft(self):
        # agy 1.2.9's `/usage` draws its own key hint over the footer, which it leaves as bare
        # as a draft's: the model footer read as unsent text before
        self.assertEqual(read("usage")[0], (None, ""))

    def test_the_composer_over_the_background_commands_is_read(self):
        # as a typed line's delivery is confirmed, and as ak's own line left there is found
        self.assertEqual(watch.composer_draft("antigravity", pane("background")), "")
        self.assertEqual(watch.composer_draft("antigravity", pane("background-draft")),
                         "draftwhiletaskruns")
        self.assertEqual(watch._composer_rows("antigravity", pane("background-draft"),
                                              exact=True), ["draft while task runs"])

    def test_a_draft_says_its_own_words_never_the_footer_or_key_hint(self):
        # the owner reads it under the seat's row; the model footer and the chooser's key hint
        # read there before
        for name, words in (("draft", "Please look at the failing test in the"),
                            ("chooser", "/us"),
                            ("background-draft", "draft while task runs")):
            with self.subTest(name):
                found = watch.classify("antigravity", watch.pane_tail(pane(name)), None, None,
                                       {}, 10000.0)
                self.assertEqual((found["state"], found["evidence"]), ("draft", words))
        # one taller than the read says the rows of it the read shows, which prove nothing whole
        for name in ("tall-line", "tall-line-and-owner-words"):
            with self.subTest(name):
                found = watch.classify("antigravity", watch.pane_tail(pane(name)), None, None,
                                       {}, 10000.0)
                self.assertEqual((found["state"], found["evidence"]),
                                 ("draft", ("20261006-1534 finished FAIL: a case. run " * 4)[:160]))
                self.assertIsNone(watch._composer_rows("antigravity", pane(name), exact=True))

    def test_the_seat_runs_under_the_wrapper(self):
        with tempfile.TemporaryDirectory(prefix=".ak-test-agy-seat-", dir=REPO) as home:
            proc = subprocess.run(
                [str(REPO / "adapters/antigravity.sh"), "interactive", "gemini-3.8-flash", "low"],
                capture_output=True, text=True,
                env={"HOME": home, "PATH": os.environ["PATH"], "AGENTKIT_SESSION": "acme"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        words = shlex.split(proc.stdout)
        self.assertEqual(words[:5], ["python3", str(REPO / "tools/idle-compact.py"),
                                     "--harness", "antigravity", "--"])
        self.assertIn("agy", words[5:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
