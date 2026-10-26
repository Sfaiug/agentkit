"""A Muse seat reads its question's answer from the conversation its own launch opened.

Muse's TUI rejects `--session-id`, so a seat opened the usual way is given no id: its launch
learns one from the SessionStart hook its line carries, which Muse fires with the session it
opened.  That session is the seat's alone: a later start in the same launch, and the launch of
another seat in the same directory, leave it as it is, and the seat reopens on it.  Two seats ask
a question each; the owner's reply, written later in one seat's session, answers that one, and
the other's stands.  Black-box: seats opened by `ak orch` from a person's terminal on a fake muse
that keeps the line it was started with, each hook fired as Muse 1.4.12 fires it -- `sh -c`, the
event's JSON on stdin, none of the seat's environment -- and each session in Muse's own store
under the Home; this test fails against `/bin/false`.
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
ASKED = {"acme": "Which schema should the acme parser write?",
         "beta": "Which branch should the acme banner land on?"}

# muse: the schema of one that runs hooks, and a TUI, the one call made on a terminal, that
# keeps the line it was started with and shows Muse's prompt.  Anything else fails, as offline.
MUSE = """#!/bin/sh
if [ "$1 $2 $3" = "schema generate-json-schema --out" ]; then
  exec printf '%s' '{{"enum": ["sessionStart", "stop", "notification"]}}' >"$4/msp.schema.json"
fi
[ -t 0 ] || exit 1
{python} -c 'import json, sys; json.dump(sys.argv[2:], open(sys.argv[1], "w"))' \\
  {root}/argv-"$AGENTKIT_SESSION".json "$@"
exec {python} {pane} {root}/prompt.txt {root}/"$AGENTKIT_SESSION".typed
"""


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class MuseQuestionConversation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        root = cls.home.root
        cls.home.fake("muse", MUSE.format(root=shlex.quote(str(root)),
                                          python=shlex.quote(sys.executable),
                                          pane=shlex.quote(str(PANE))))
        (root / "prompt.txt").write_text((FIXTURES / "muse-prompt-pane.txt").read_text())

    def launch(self, name, *opening):
        """Open a Muse seat as a person does, and the line its muse was started with; a seat
        opened before is reopened by its name alone."""
        argv = self.home.root / f"argv-{name}.json"
        argv.unlink(missing_ok=True)
        term = Terminal(self.home, "orch", name, *opening, size=(120, 40))
        deadline = time.monotonic() + 60
        while not argv.exists() or not argv.read_text().endswith("]"):
            if time.monotonic() > deadline:
                raise AssertionError(f"no muse started for {name}; the terminal shows:\n"
                                     f"{term.screen()}")
            time.sleep(0.05)
        return json.loads(argv.read_text())

    def start(self, argv, session, source="startup"):
        """Muse opens `session`: it fires each SessionStart hook its line was given, and writes
        the session's opening prompt in its store, a minute before now."""
        hooks = [hook["command"] for flag, value in zip(argv, argv[1:])
                 if flag == "-c" and value.startswith("hooks.SessionStart=")
                 for group in json.loads(value.partition("=")[2]) for hook in group["hooks"]]
        self.assertTrue(hooks, argv)
        payload = {"hook_event_name": "SessionStart", "session_id": session, "source": source,
                   "cwd": str(self.home.path), "transcript_path": None, "model": "unknown"}
        for hook in hooks:
            done = self.home.run("sh", "-c", hook, input=json.dumps(payload))
            self.assertEqual(done.code, 0, done.err)
        log = self.log(session)
        if not log.exists():
            log.parent.mkdir(parents=True)
            self.said(session, "Build the acme parser.", time.time() - 60)

    def log(self, session):
        return self.home.path / ".local/share/muse/sessions/2026/10/24" / session / "session.jsonl"

    def said(self, session, text, at, event=None):
        """The user side of that session typed `text` at `at`, as Muse records a run's prompt, or
        the model said what `event` holds."""
        line = {"schema_version": 1, "stream": {"kind": "session", "id": session},
                "record_type": "event", "recorded_at": round(at * 1_000_000),
                "payload": {"kind": "run", "run_id": uuid.uuid4().hex,
                            "event": event or {"kind": "started", "prompt": text}}}
        with self.log(session).open("a") as fh:
            fh.write(json.dumps(line) + "\n")

    def standing(self, name):
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        return ASKED[name] in done.out

    def test_a_reply_in_its_own_session_answers_only_its_question(self):
        sessions = {name: str(uuid.uuid4()) for name in ASKED}
        lines = {name: self.launch(name, *NEW) for name in ASKED}
        for name, session in sessions.items():
            self.start(lines[name], session)
        # a later start in either launch, and another seat's, change no seat's session
        self.start(lines["beta"], str(uuid.uuid4()), source="clear")
        self.start(lines["acme"], sessions["beta"])
        for name, question in ASKED.items():
            done = self.home.ak("notify", "needs", question, "--session", name)
            self.assertEqual(done.code, 0, done.err)
            self.said(sessions[name], question, time.time(), {"kind": "assistant_message_committed",
                                                               "text": question})
        self.assertTrue(all(self.standing(name) for name in ASKED))

        self.said(sessions["acme"], "Write the v2 schema.", time.time())
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertFalse(self.standing("acme"), "the owner's reply left its question standing")
        self.assertTrue(self.standing("beta"), "another seat's reply answered its question")

    def test_a_seat_reopens_on_the_session_its_launch_opened(self):
        session = str(uuid.uuid4())
        self.start(self.launch("gamma", *NEW), session)
        done = self.home.tmux("kill-session", "-t", "=gamma")
        self.assertEqual(done.code, 0, done.err)
        argv = self.launch("gamma")
        self.assertEqual(argv[argv.index("resume") + 1], session, argv)


if __name__ == "__main__":
    unittest.main()
