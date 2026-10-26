"""A Muse seat's hooks reach its look, and every screen a live sweep of Muse Code 1.4.7 found
misread reads as what the seat is doing.

Muse hands a hook almost none of the seat's environment, `TMUX` and `TMUX_PANE` among what it
drops, so hooks/seat-state.sh never started a look: the seat's launch now writes both into the
hook's command as its pane starts.  A question answered fires `PostToolBatch` naming its tool
inside the batch, and Esc on it only `Interrupt`, so the question stood until a tick; its
notice names the folder, not the question; its review step, a draft wrapped onto a second row,
a launch without yolo, the status line's own words and the `/model` and `/resume` pickers all
read wrong.  Each case is a real capture of a seat, renamed, and the payload Muse handed its
hook there, run through the hook command the seat's own launch line installs.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from fixtures.sandbox import REPO
from agentkit import config, watch

SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
QUESTION, REMINDED, ANSWERED, STOPPED, ESCAPED, APPROVAL = (
    json.loads(line) for line in (FIX / "muse-hook-payloads.jsonl").read_text(
        encoding="utf-8").splitlines())
TMUX, PANE = "/tmp/tmux 1000/acme,4242,0", "%7"     # a socket path a shell has to quote


def pane(what):
    return (FIX / f"muse-{what}-pane.txt").read_text(encoding="utf-8")


def read(what, fact=None):
    """(screen_state, classify) of that capture, with that hook fact recorded."""
    return read_pane(pane(what), fact)


def read_pane(text, fact=None):
    tail = watch.pane_tail(text)
    return watch.screen_state("muse", tail)[:2], watch.classify(
        "muse", tail, fact or {}, None, {}, (fact or {}).get("at", 0) + 1)


class Seat(unittest.TestCase):
    """A seat launched by `adapters/muse.sh interactive` in a pane, whose muse runs its hooks."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.home = Path(tmp.name)
        launch, hook = cls.home / "launch-bin", cls.home / "hook-bin"
        launch.mkdir()
        hook.mkdir()
        # muse: a schema that has hooks, and a TUI that writes down the line it was started with
        (launch / "muse").write_text(
            "#!/bin/sh\n"
            'if [ "$1 $2 $3" = "schema generate-json-schema --out" ]; then\n'
            "  printf '%s' '{\"enum\": [\"stop\", \"notification\"]}' >\"$4/msp.schema.json\"\n"
            "  exit 0\nfi\n"
            f"exec {shlex.quote(shutil.which('python3'))} -c "
            "'import json, sys; json.dump(sys.argv[2:], open(sys.argv[1], \"w\"))' "
            f"{shlex.quote(str(cls.home / 'argv.json'))} \"$@\"\n")
        # tmux: the pane as `capture-pane -p` prints it, without colours
        (cls.home / "pane.txt").write_text(watch.strip_sgr(pane("question-asked")))
        (hook / "tmux").write_text(
            "#!/bin/sh\n"
            'printf \'%s\\n\' "$*" >>"$HOME/tmux.log"\n'
            '[ "$1" = capture-pane ] && exec cat "$HOME/pane.txt"\nexit 1\n')
        # bash: notes what reaches hooks/seat-state.sh, then runs it with no server, so no look
        # of a seat this sandbox does not have is started
        (hook / "bash").write_text(
            "#!/bin/sh\n"
            'case ${1-} in */hooks/seat-state.sh)\n'
            '  printf \'%s\\n\' "${TMUX-}" "${TMUX_PANE-}" "${AGENTKIT_SESSION-}" '
            '>"$HOME/reached"\n'
            f"  TMUX= TMUX_PANE= exec {shlex.quote(shutil.which('bash'))} \"$@\" ;;\nesac\n"
            f"exec {shlex.quote(shutil.which('bash'))} \"$@\"\n")
        # timeout: a host without coreutils' -- stock macOS -- has none that runs
        (hook / "timeout").write_text("#!/bin/sh\nexit 127\n")
        for fake in (launch / "muse", hook / "tmux", hook / "bash", hook / "timeout"):
            fake.chmod(0o755)
        cls.hook_path = f"{hook}:{os.environ['PATH']}"
        rulebook = cls.home / "rules.md"
        rulebook.write_text("rules\n")
        line = subprocess.run(
            ["bash", str(REPO / "adapters/muse.sh"), "interactive", "muse-spark-1.3", "minimal"],
            capture_output=True, text=True, timeout=30, check=True,
            env={**os.environ, "PATH": f"{launch}:{os.environ['PATH']}",
                 "AGENTKIT_RULEBOOK": str(rulebook), "AGENTKIT_ACCOUNT": "",
                 "AGENTKIT_SESSION": SEAT}).stdout
        words = shlex.split(line)
        # the line as the seat's pane runs it, with no idle-compact wrapper around its harness
        wrapper = words.index(str(REPO / "tools/idle-compact.py"))
        subprocess.run(words[:wrapper - 1] + words[words.index("--") + 1:], timeout=30, check=True,
                       env={**os.environ, "PATH": f"{launch}:{os.environ['PATH']}",
                            "TMUX": TMUX, "TMUX_PANE": PANE})
        argv = json.loads((cls.home / "argv.json").read_text())
        cls.hooks = dict(argv[at + 1].split("=", 1) for at, word in enumerate(argv)
                         if word == "-c" and argv[at + 1].startswith("hooks."))
        # the seat's record, so its hook knows the harness, as on a real seat
        state = cls.home / ".agentkit/state"
        state.mkdir(parents=True)
        (state / f"session-{SEAT}.json").write_text(
            json.dumps({"orchestrator": "spark", "workers": ["spark"]}))

    def fire(self, payload):
        """Muse runs that event's hook with that payload: its command, in a shell, with only
        the environment Muse hands a hook.  The fact it writes down, or None."""
        fact = self.home / f".agentkit/state/hook-{SEAT}.json"
        fact.unlink(missing_ok=True)
        (handlers,) = json.loads(self.hooks[f"hooks.{payload['hook_event_name']}"])
        (handler,) = handlers["hooks"]
        subprocess.run(["sh", "-c", handler["command"]], input=json.dumps(payload), text=True,
                       timeout=60, check=True,
                       env={"HOME": str(self.home), "PATH": self.hook_path,
                            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
        return json.loads(fact.read_text()) if fact.exists() else None


class HooksReachTheLook(Seat):

    def test_every_event_its_manifest_maps_is_installed(self):
        mapped = {entry["name"] for entry in config.manifest("muse")["hooks"]["event"]}
        # and SessionStart, which writes the session it opened into the launch's receipt
        self.assertEqual({name.split(".", 1)[1] for name in self.hooks}, mapped | {"SessionStart"})
        # Muse runs an Interrupt hook only alongside the turn
        (handlers,) = json.loads(self.hooks["hooks.Interrupt"])
        self.assertIs(handlers["hooks"][0].get("async"), True)

    def test_each_hook_hands_its_look_the_seat_s_pane_and_server(self):
        for payload in (QUESTION, ANSWERED, STOPPED, ESCAPED):
            with self.subTest(event=payload["hook_event_name"]):
                (self.home / "reached").unlink(missing_ok=True)
                self.fire(payload)
                self.assertEqual((self.home / "reached").read_text().splitlines(),
                                 [TMUX, PANE, SEAT])


class TheQuestion(Seat):

    def test_its_reason_is_the_question_on_the_screen_not_the_folder(self):
        fact = self.fire(QUESTION)
        self.assertEqual(QUESTION["message"], "ws — waiting for your answer")
        self.assertIn(f"capture-pane -p -J -t {PANE}",
                      (self.home / "tmux.log").read_text().splitlines())
        found = read("question-asked", fact)[1]
        self.assertEqual((found["state"], found["authority"], found["evidence"]),
                         ("asking", "hook", "Which colour do you prefer, red or blue?"))

    def test_an_answer_gives_the_turn_back(self):
        fact = self.fire(ANSWERED)
        self.assertEqual(watch.hook_state("muse", fact)[:2],
                         ("working", "PostToolBatch/request_user_input"))
        self.assertEqual(read("question-answered", fact)[1]["state"], "working")

    def test_the_batches_its_reminders_run_beside_it_say_nothing(self):
        self.assertIsNone(self.fire(REMINDED))

    def test_esc_puts_it_down_whatever_reads_next(self):
        fact = self.fire(ESCAPED)
        self.assertEqual(watch.hook_state("muse", fact)[0], "at_prompt")
        for what, state in (("question-escaped", "at_prompt"), ("model-picker", "draft"),
                            ("compacting", "working")):
            with self.subTest(screen=what):
                self.assertEqual(read(what, fact)[1]["state"], state)

    def test_its_review_step_still_asks(self):
        fact = self.fire(QUESTION)
        seen, found = read("question-review", fact)
        self.assertEqual(seen, (None, ""))
        self.assertEqual((found["state"], found["authority"]), ("asking", "hook"))
        # whichever row holds its cursor -- an answer to edit, Submit or Interrupt -- a line
        # typed there, and its Enter, would land on it
        drawn = watch.strip_sgr(pane("question-review")).replace("  ⟩ Submit answers",
                                                                "    Submit answers")
        for row in ("Colour: red", "Size: small", "Submit answers", "Interrupt turn"):
            with self.subTest(cursor=row):
                self.assertEqual(read_pane(drawn.replace(f"    {row}", f"  ⟩ {row}"),
                                           fact)[1]["state"], "asking")


class WithoutYolo(Seat):

    def test_its_idle_prompt_is_a_prompt(self):
        for what in ("autoreview-idle", "overrides-idle"):
            with self.subTest(screen=what):
                self.assertEqual(read(what)[0], ("at_prompt", "prompt.composer"))

    def test_its_approval_dialog_asks(self):
        fact = self.fire(APPROVAL)
        self.assertEqual(watch.hook_state("muse", fact)[:2],
                         ("asking", "Notification/permission_prompt"))
        # its choices are no composer and no draft: it asks from the moment it is drawn
        self.assertEqual(read("approval")[0], ("asking", "asking.approval"))
        self.assertEqual(read("approval", fact)[1]["state"], "asking")


class Screens(unittest.TestCase):

    def test_a_draft_wrapped_onto_a_second_row_is_a_draft(self):
        seen, found = read("draft-wrapped")
        self.assertEqual(seen, ("draft", "prompt.draft"))
        self.assertTrue(found["evidence"].startswith("acme long draft words"), found["evidence"])

    def test_its_status_line_s_own_words_read_as_what_it_does(self):
        for what, state in (("interrupting", "working"), ("compacting", "working"),
                            ("steering", "working"), ("compacted", "at_prompt")):
            with self.subTest(screen=what):
                self.assertEqual(read(what)[0][0], state)

    def test_a_dialog_s_words_typed_or_said_are_no_dialog(self):
        raw = pane("tray-draft")
        # the review step's last two choices too, quoted on a reply's two rows
        for words in ("Interrupt turn", "Submit answers", "Submit answers\n  Interrupt turn",
                      "Change approval defaults in /permissions"):
            with self.subTest(words=words):
                typed = raw.replace("acme draft words", f"Explain {words}")
                said = raw.replace("acme draft words", "").replace("DONE", f"I updated {words}")
                self.assertEqual(read_pane(typed)[0], ("draft", "prompt.draft"))
                self.assertEqual(read_pane(said)[0][0], "at_prompt")

    def test_the_owner_s_own_pickers_are_never_typed_into(self):
        for what in ("model-picker", "resume-picker"):
            with self.subTest(screen=what):
                self.assertEqual(read(what)[0], ("draft", "prompt.picker"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
