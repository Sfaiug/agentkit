"""A Muse seat follows its conversation through Muse's own `/new`.

`/new` fires no hook: the SessionStart hooks on a launch's line ran in the session it opened and
not in the next.  What moves is Muse's registry under its data home, `runtime/muse/sessions/`,
where the entry naming the launch's process goes and one for the new session, the same process
holding it, takes its place.  A question asked there, then the owner's reply written in that new
session's store, answers it; another seat in the same directory, its own Muse with its own
entry, keeps its question; and the seat reopens on the new session.  Black-box: seats opened by
`ak orch` from a person's terminal on a fake muse that fires each SessionStart hook its line
carries as Muse 1.4.12 does -- its own child, `sh -c`, the event's JSON on stdin, none of the
seat's environment -- and writes its registry entry and session as Muse does, under the Home;
this test fails against `/bin/false`.
"""

import json
import shlex
import sys
import time
import uuid
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE
from fixtures.akterm import Terminal

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NEW = ("--model", "spark", "--workers", "spark")    # a seat opened anew, on Muse
ASKED = {"acme": "Which layout should the acme dashboard take?",
         "beta": "Which branch should the acme banner land on?"}
DAY = ".local/share/muse/sessions/2026/10/24"
REGISTRY = ".local/share/muse/runtime/muse/sessions"

# muse: the schema of one that runs hooks, and a TUI, the one call made on a terminal.
# Anything else fails, as offline.
MUSE = """#!/bin/sh
if [ "$1 $2 $3" = "schema generate-json-schema --out" ]; then
  exec printf '%s' '{{"enum": ["sessionStart", "stop", "notification"]}}' >"$4/msp.schema.json"
fi
[ -t 0 ] || exit 1
exec {python} {tui} "$@"
"""

# The TUI: opens a session (the one `resume` names, or a new one), lists it in the registry under
# its own pid, fires its line's SessionStart hooks, says which in `<seat>.json`, and becomes the
# pane showing Muse's prompt -- the same process, as Muse stays the one holding it.
TUI = """import json, os, subprocess, sys, time, uuid
from pathlib import Path
root, home, argv = Path({root!r}), Path(os.environ["HOME"]), sys.argv[1:]
seat = os.environ["AGENTKIT_SESSION"]
session = argv[argv.index("resume") + 1] if "resume" in argv else str(uuid.uuid4())
registry = home / {registry!r}
registry.mkdir(parents=True, exist_ok=True)
(registry / f"{{session}}.json").write_text(json.dumps({{"schema_version": 1, "session_id": session,
    "endpoint_hint": f"ms-{{uuid.uuid4().hex[:12]}}.sock", "target_eligibility": "message_capable",
    "process_generation_hint": f"pid={{os.getpid()}}"}}))
payload = json.dumps({{"hook_event_name": "SessionStart", "session_id": session,
                      "source": "resume" if "resume" in argv else "startup",
                      "cwd": os.getcwd(), "transcript_path": None, "model": "unknown"}})
for flag, value in zip(argv, argv[1:]):
    if flag == "-c" and value.startswith("hooks.SessionStart="):
        for group in json.loads(value.partition("=")[2]):
            for hook in group["hooks"]:
                subprocess.run(["sh", "-c", hook["command"]], input=payload, text=True,
                               env={{"HOME": str(home), "PATH": os.environ["PATH"]}})
log = home / {day!r} / session / "session.jsonl"
if not log.exists():
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({{"schema_version": 1, "stream": {{"kind": "session", "id": session}},
        "record_type": "event", "recorded_at": round((time.time() - 60) * 1_000_000),
        "payload": {{"kind": "run", "run_id": uuid.uuid4().hex,
                    "event": {{"kind": "started", "prompt": "Build the acme parser."}}}}}}) + "\\n")
(root / f"{{seat}}.json").write_text(json.dumps({{"argv": argv, "pid": os.getpid(),
                                                  "session": session}}))
os.execv(sys.executable, [sys.executable, {pane!r}, str(root / "prompt.txt"),
                          str(root / f"{{seat}}.typed")])
"""


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class MuseQuestionAfterNew(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        root = cls.home.root
        tui = root / "tui.py"
        tui.write_text(TUI.format(root=str(root), day=DAY, registry=REGISTRY, pane=str(PANE)))
        cls.home.fake("muse", MUSE.format(python=shlex.quote(sys.executable),
                                          tui=shlex.quote(str(tui))))
        (root / "prompt.txt").write_text((FIXTURES / "muse-prompt-pane.txt").read_text())

    def launch(self, name, *opening):
        """Open a Muse seat as a person does: what its muse said it opened, once it has."""
        started = self.home.root / f"{name}.json"
        started.unlink(missing_ok=True)
        term = Terminal(self.home, "orch", name, *opening, size=(120, 40))
        deadline = time.monotonic() + 60
        while not started.exists() or not started.read_text().endswith("}"):
            if time.monotonic() > deadline:
                raise AssertionError(f"no muse started for {name}; the terminal shows:\n"
                                     f"{term.screen()}")
            time.sleep(0.05)
        return json.loads(started.read_text())

    def new(self, muse):
        """The owner types `/new`: the same Muse opens another session, at another endpoint,
        and its registry entry moves there; no hook runs."""
        session = str(uuid.uuid4())
        registry = self.home.path / REGISTRY
        (registry / f"{muse['session']}.json").unlink()
        self.home.write(f"{REGISTRY}/{session}.json", {
            "schema_version": 1, "session_id": session, "endpoint_hint": "ms-0a0b0c0d0e0f.sock",
            "target_eligibility": "message_capable",
            "process_generation_hint": f"pid={muse['pid']}"})
        self.said(session, "Lay out the acme dashboard.", time.time() - 30)
        return session

    def said(self, session, text, at):
        """The user side of that session typed `text` at `at`, as Muse records a run's prompt."""
        log = self.home.path / DAY / session / "session.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        line = {"schema_version": 1, "stream": {"kind": "session", "id": session},
                "record_type": "event", "recorded_at": round(at * 1_000_000),
                "payload": {"kind": "run", "run_id": uuid.uuid4().hex,
                            "event": {"kind": "started", "prompt": text}}}
        with log.open("a") as fh:
            fh.write(json.dumps(line) + "\n")

    def standing(self, name):
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        return ASKED[name] in done.out

    def test_a_reply_after_new_answers_its_question_and_the_seat_reopens_there(self):
        muses = {name: self.launch(name, *NEW) for name in ASKED}
        session = self.new(muses["acme"])
        for name, question in ASKED.items():
            done = self.home.ak("notify", "needs", question, "--session", name)
            self.assertEqual(done.code, 0, done.err)
        self.assertTrue(all(self.standing(name) for name in ASKED))

        self.said(session, "Wide.", time.time())
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertFalse(self.standing("acme"), "the owner's reply after /new left it standing")
        self.assertTrue(self.standing("beta"), "another seat's reply answered its question")

        done = self.home.tmux("kill-session", "-t", "=acme")
        self.assertEqual(done.code, 0, done.err)
        argv = self.launch("acme")["argv"]
        self.assertEqual(argv[argv.index("resume") + 1], session, argv)


if __name__ == "__main__":
    unittest.main()
