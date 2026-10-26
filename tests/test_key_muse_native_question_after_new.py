"""A Muse seat needs its owner while its own question card blocks, `/new` or not.

`/new` drops the hooks on a launch's line, so the session it opens fires no Notification and no
PostToolBatch; Muse still logs each card going up and its settling, answered or interrupted, as
run events of the session the seat owns.  The card on screen reads `needs you` in its own words;
its own settling ends that wait, and only its own: an older card's does not, nor a request in
another session or quoted in a message.  An Esc rests the seat, its plan unfinished, until its
next prompt.  A settled card stays closed, its seat neither reopened to ask it again after its
process dies nor shown it once reopened on that session.  Black-box: a seat opened by `ak orch`
from a person's terminal on a fake muse that fires its line's SessionStart hooks as Muse 1.4.12
does and lists its sessions in Muse's registry, its log in Muse's store, under the Home; this
test fails against `/bin/false`.
"""

import json
import shlex
import sys
import time
import uuid
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, PLAN_LINE
from fixtures.akterm import Terminal

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ASKED = "Which shape should acme use?"
DAY = ".local/share/muse/sessions/2026/10/26"
REGISTRY = ".local/share/muse/runtime/muse/sessions"

MUSE = """#!/bin/sh
if [ "$1 $2 $3" = "schema generate-json-schema --out" ]; then
  exec printf '%s' '{{"enum": ["sessionStart", "stop", "notification"]}}' >"$4/msp.schema.json"
fi
[ -t 0 ] || exit 1
exec {python} {tui} "$@"
"""

# Opens the session `resume` names, or a new one, fires its line's SessionStart hooks, lists the
# session under its own pid, says which in `<seat>.json`, and becomes the pane showing `screen`.
TUI = """import json, os, subprocess, sys, uuid
from pathlib import Path
root, home, argv = Path({root!r}), Path(os.environ["HOME"]), sys.argv[1:]
seat = os.environ["AGENTKIT_SESSION"]
session = argv[argv.index("resume") + 1] if "resume" in argv else str(uuid.uuid4())
payload = json.dumps({{"hook_event_name": "SessionStart", "session_id": session,
                      "source": "resume" if "resume" in argv else "startup",
                      "cwd": os.getcwd(), "transcript_path": None, "model": "unknown"}})
for flag, value in zip(argv, argv[1:]):
    if flag == "-c" and value.startswith("hooks.SessionStart="):
        for group in json.loads(value.partition("=")[2]):
            for hook in group["hooks"]:
                subprocess.run(["sh", "-c", hook["command"]], input=payload, text=True,
                               env={{"HOME": str(home), "PATH": os.environ["PATH"]}})
registry = home / {registry!r}
registry.mkdir(parents=True, exist_ok=True)
(registry / f"{{session}}.json").write_text(json.dumps({{"schema_version": 1, "session_id": session,
    "endpoint_hint": "ms-0a0b0c0d0e0f.sock", "target_eligibility": "message_capable",
    "process_generation_hint": f"pid={{os.getpid()}}"}}))
(root / f"{{seat}}.json").write_text(json.dumps({{"argv": argv, "pid": os.getpid(),
                                                  "session": session}}))
os.execv(sys.executable, [sys.executable, {pane!r}, str(root / "screen.txt"),
                          str(root / f"{{seat}}.typed")])
"""


def card(prompt, kind, **fields):
    """A card's event as Muse 1.4.12 logs it, named by its prompt and its tool call."""
    return {"kind": f"user_input_prompt_{kind}", "prompt_id": prompt,
            "tool_call_id": f"{prompt}-call", **fields}


ASK = {"tool_name": "request_user_input", "questions": [
    {"id": "shape", "header": "Shape", "question": ASKED,
     "options": [{"label": "Round (Recommended)"}, {"label": "Square"}]}]}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class MuseNativeQuestionAfterNew(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        root = self.home.root
        tui = root / "tui.py"
        tui.write_text(TUI.format(root=str(root), registry=REGISTRY, pane=str(PANE)))
        self.home.fake("muse", MUSE.format(python=shlex.quote(sys.executable),
                                           tui=shlex.quote(str(tui))))
        self.show("muse-prompt-pane.txt")
        # no audit seat of ak's own, nor a collection due, to outlive a tick's box
        akconfig.write(self.home, ["opus", "spark"])
        self.home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        # the owner's own session keeps ak's tmux server up outside the box: a seat a tick
        # reopened is still there once the tick has ended
        done = self.home.tmux("-f", "/dev/null", "new-session", "-d", "-s", "notes", "sleep 3600")
        self.assertEqual(done.code, 0, done.err)

    def show(self, fixture):
        screen = (FIXTURES / fixture).read_text()
        (self.home.root / "screen.txt").write_text(
            screen.replace("Which colour should the acme banner use?", ASKED))

    def esc(self, session, prompt):
        """The owner presses Esc on that card: Muse puts it down as it logs it settled, so a
        look between the two reads either the card up or no card at all, never a screen
        nothing reads."""
        self.show("muse-prompt-pane.txt")
        self.drawn()
        self.logs(session, card(prompt, "settled", outcome="interrupted"))

    def drawn(self):
        """Once the seat's pane shows Muse's prompt whole: its status line, and no card."""
        deadline = time.monotonic() + 30
        while (not (screen := self.home.tmux("capture-pane", "-p", "-t", "=acme:").out)
                .rstrip().endswith("YOLO") or "to interrupt" in screen):
            self.assertLess(time.monotonic(), deadline, "the prompt was never drawn")
            time.sleep(0.05)

    def launch(self, *opening):
        started = self.home.root / "acme.json"
        started.unlink(missing_ok=True)
        term = Terminal(self.home, "orch", "acme", *opening, size=(120, 40))
        deadline = time.monotonic() + 60
        while not started.exists() or not started.read_text().endswith("}"):
            if time.monotonic() > deadline:
                raise AssertionError(f"no muse started; the terminal shows:\n{term.screen()}")
            time.sleep(0.05)
        return json.loads(started.read_text())

    def new(self, muse):
        """The owner types `/new`: the same Muse moves to another session; no hook runs."""
        session = str(uuid.uuid4())
        (self.home.path / REGISTRY / f"{muse['session']}.json").unlink()
        self.home.write(f"{REGISTRY}/{session}.json", {
            "schema_version": 1, "session_id": session, "endpoint_hint": "ms-0a0b0c0d0e0f.sock",
            "target_eligibility": "message_capable",
            "process_generation_hint": f"pid={muse['pid']}"})
        return session

    def logs(self, session, *events):
        log = self.home.path / DAY / session / "session.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            for event in events:
                fh.write(json.dumps({
                    "schema_version": 1, "stream": {"kind": "session", "id": session},
                    "record_type": "event", "recorded_at": round(time.time() * 1_000_000),
                    "payload": {"kind": "run", "run_id": "acme-run", "event": event}}) + "\n")

    def reads(self, word):
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines()[0], f"acme  {word}", done.out)
        return done.out

    def test_its_own_card_blocks_until_that_card_settles(self):
        muse = self.launch("--model", "spark", "--workers", "spark")
        self.home.write(".agentkit/state/plan-acme.md", PLAN_LINE + "\n")     # work owed
        self.logs(muse["session"], {"kind": "started", "prompt": "Build the acme parser."},
                  {"kind": "terminal", "terminal": "completed"})
        session = self.new(muse)
        self.logs(session, {"kind": "started", "prompt": "Shape the acme logo."})

        self.show("muse-working-pane.txt")
        self.logs(muse["session"], card("old-prompt", "requested", **ASK))
        self.logs(session, {"kind": "assistant_message_committed", "phase": "commentary",
                            "text": json.dumps(card("quoted", "requested", **ASK))})
        self.reads("working")       # another session's card, and one quoted, block nothing

        self.show("muse-question-pane.txt")
        self.logs(session, {"kind": "assistant_message_committed", "phase": "commentary",
                            "text": f"{ASKED}\n\n- Round (Recommended)\n- Square"},
                  card("acme-prompt", "requested", **ASK))
        self.assertIn(f"reason:    {ASKED}", self.reads("needs you"))

        self.logs(session, card("acme-prompt", "settled", outcome="answered",
                                answers=[{"id": "shape", "selected_label": "Round (Recommended)"}]))
        self.show("muse-working-pane.txt")
        self.reads("working")

        self.show("muse-question-pane.txt")
        self.logs(session, card("next-prompt", "requested", **ASK),
                  card("acme-prompt", "settled", outcome="answered", answers=[]))
        self.reads("needs you")     # an older card's settling leaves the newer one up
        self.esc(session, "next-prompt")
        self.assertNotIn(ASKED, self.reads("idle"))
        self.logs(session, {"kind": "started", "prompt": "Make it round."},
                  {"kind": "terminal", "terminal": "completed"})
        self.reads("needs you")     # its next prompt ended the rest: its plan is owed again

        self.show("muse-question-pane.txt")
        self.logs(session, card("last-prompt", "requested", **ASK))
        self.reads("needs you")
        self.esc(session, "last-prompt")
        done = self.home.tmux("kill-session", "-t", "=acme")
        self.assertEqual(done.code, 0, done.err)
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        seat = json.loads((self.home.path / ".agentkit/state/seat-acme.json").read_text())
        self.assertNotIn("reopened_at", seat, "the tick reopened it to ask its settled card again")
        argv = self.launch()["argv"]
        self.assertEqual(argv[argv.index("resume") + 1], session, argv)
        self.reads("idle")          # its settled card stays closed on the reopened session


if __name__ == "__main__":
    unittest.main()
