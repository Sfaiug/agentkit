"""A question Muse asks with its own tool reads as asking, from the hook its dialog fires.

Muse 1.4.7's `Request user input` draws its options and a key hint ending `Esc to interrupt` over
a composer it keeps open: the working rule read that hint, so the seat said `working`, no card
went out, and the turn waited on an answer nobody was told about.  Reading the hint instead
lost three review rounds to output quoting it (#878).  The dialog's opening is a Notification
of its own kind, `question_prompt`, which no text on the screen can fake: that decides it, the
seat's launch carries the hook that writes it down, and the hint no longer reads as working.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from fixtures.sandbox import REPO
from agentkit import watch

FIX = REPO / "tests/fixtures"
QUESTION = (FIX / "muse-question-pane.txt").read_text(encoding="utf-8")
WORKING = (FIX / "muse-working-pane.txt").read_text(encoding="utf-8")
PROMPT = (FIX / "muse-prompt-pane.txt").read_text(encoding="utf-8")
HINT = ("Enter to select · ↑/↓ to move · ←/→ to switch question · Tab for an optional note · "
        "Esc to interrupt")
ASKED = {"event": "Notification", "kind": "question_prompt", "at": 100.0}


def read(pane, fact):
    return watch.classify("muse", watch.pane_tail(pane), fact, None, {}, 200.0)


class MuseQuestion(unittest.TestCase):

    def test_its_dialog_opening_reads_as_asking(self):
        found = read(QUESTION, ASKED)
        self.assertEqual((found["state"], found["authority"]), ("asking", "hook"))
        # its options are indented, so one quoting the spinner keeps the question up
        quoting = QUESTION.replace("Optionally, add details in notes (tab).",
                                   "Use the text (0s · esc to interrupt)")
        self.assertEqual(read(quoting, ASKED)["state"], "asking")

    def test_no_text_on_the_screen_asks(self):
        # the dialog itself, with no hook having said so, and output quoting its hint
        self.assertNotEqual(read(QUESTION, {})["state"], "asking")
        quoted = WORKING.replace("◇ Thinking", f"{HINT}\n◇ Thinking", 1)
        self.assertEqual(read(quoted, {})["state"], "working")

    def test_an_answered_question_gives_way_to_the_turn_and_the_prompt(self):
        self.assertEqual(read(WORKING, ASKED)["state"], "working")
        self.assertEqual(read(PROMPT, ASKED)["state"], "at_prompt")


class MuseLaunch(unittest.TestCase):
    """The seat's launch line carries the hook only where its muse's own schema has hooks."""

    def launch(self, schema, *resume):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)
            (fake / "muse").write_text(
                "#!/bin/bash\n"
                '[ "$1 $2 $3" = "schema generate-json-schema --out" ] || exit 0\n'
                + (f"printf '%s' '{schema}' >\"$4/msp.schema.json\"\n" if schema else "exit 2\n"))
            (fake / "muse").chmod(0o755)
            (fake / "rules.md").write_text("rules\n")
            proc = subprocess.run(
                ["bash", str(REPO / "adapters/muse.sh"), "interactive", "muse-spark-1.3",
                 "minimal", *resume], capture_output=True, text=True, timeout=30,
                env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}",
                     "HOME": str(fake),
                     "AGENTKIT_RULEBOOK": str(fake / "rules.md"), "AGENTKIT_ACCOUNT": "",
                     "AGENTKIT_SESSION": "fix-api"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return shlex.split(proc.stdout)

    def test_native_questions_are_available_on_open_and_resume(self):
        # Muse 1.4.11's --yolo now withholds request_user_input, too. Keep its
        # workspace access by naming those controls without disabling questions.
        for resume in ((), ("acme-session",)):
            with self.subTest(resume=resume):
                cmd = self.launch('{"enum": ["notification"]}', *resume)
                for flag in ("--trust-workspace", "--disable-approval", "--disable-sandbox"):
                    self.assertIn(flag, cmd)
                self.assertNotIn("--yolo", cmd)
                self.assertNotIn("--disable-request-user-input", cmd)
                if resume:
                    self.assertEqual(cmd[cmd.index("resume") + 1], resume[0])

    def test_a_muse_with_hooks_runs_the_seat_hook_on_its_events(self):
        cmd = self.launch('{"enum": ["userPromptSubmit", "stop", "notification"]}')
        hooks = [cmd[i + 1] for i, arg in enumerate(cmd)
                 if arg == "-c" and cmd[i + 1].startswith("hooks.")]
        self.assertEqual([hook.split("=", 1)[0] for hook in hooks],
                         ["hooks.Stop", "hooks.Notification", "hooks.PostToolBatch",
                          "hooks.Interrupt"])
        # a hook gets almost none of the seat's environment: its name rides in the command
        for hook in hooks:
            self.assertIn(f"AGENTKIT_SESSION=fix-api bash {REPO / 'adapters/muse.sh'} hook", hook)

    def test_its_prompts_stay_unreported(self):
        # a seat that reports prompts has only them answer its questions: one opened before
        # its launch carried hooks, or on an older muse, reports none
        from agentkit import harness
        self.assertIsNone(harness.load("muse").prompt_hook)

    def test_a_muse_without_them_launches_as_before(self):
        for schema in ("", '{"enum": ["sessionStart", "stop"]}'):
            with self.subTest(schema=schema):
                self.assertNotIn("-c", self.launch(schema))


if __name__ == "__main__":
    unittest.main(verbosity=2)
