"""A Muse seat's hooks run in the session `/new` opens, from Muse's settings file.

The file, wired as install.sh wires it beside the owner's own hook, carries the seat's events.  A
seat's turn ends, `/new`, a turn ends there: the seat names that session, keeps the one it left
and reopens in it, and the owner's hook heard the turn.  The owner's own Muse outside ak, naming
no seat though its shell does, and one in a window of the seat's, naming the seat, fire the same
hook in their sessions, `/new`'s too, and no seat's state file changes.  Black-box on `AK_BIN`,
on a fake muse firing hooks as Muse 1.4.20 does (tests/fixtures/musetui.py); this fails against
`/bin/false`, and on a settings file carrying none of ak's hooks.
"""

import json
import shlex
import sys
import time
import uuid
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import musetui
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

STORE = ".local/share/muse/sessions/2026/11/14"
# the owner's own, already in Muse's settings file: it writes down each turn's end it hears
OWN = {"type": "command", "command": '{ cat; echo; } >>"$HOME/heard.jsonl"'}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MuseHooksAfterNew(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        home.write(".config/muse/settings.json", {"schema_version": 1, "tui": {"theme": "dark"},
                                                  "hooks": {"Stop": [{"hooks": [OWN]}]}})
        musetui.install(home)
        term = Terminal(home, "orch", "acme", "--model", "spark", "--workers", "spark",
                        size=(120, 40))
        try:
            self.a = musetui.started(home, "acme")["session"]
        except AssertionError:
            raise AssertionError(f"no muse started; the terminal shows:\n{term.screen()}") from None
        self.turn("acme", self.a)
        self.b = str(uuid.uuid4())      # `/new`
        self.turn("acme", self.b)

    def turn(self, muse, session):
        """The owner asks for something in that session, logged with Muse's answer in its store,
        and that Muse ends the turn there."""
        log = self.home.path / STORE / session / "session.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            for event in ({"kind": "started", "prompt": "Add a retry button."},
                          {"kind": "assistant_message_committed", "text": "Done."}):
                fh.write(json.dumps({
                    "schema_version": 1, "stream": {"kind": "session", "id": session},
                    "record_type": "event", "recorded_at": round(time.time() * 1e6),
                    "payload": {"kind": "run", "run_id": uuid.uuid4().hex, "event": event}}) + "\n")
        musetui.stop(self.home, muse, session)

    def record(self):
        return json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())

    def heard(self):
        """The sessions whose turn's end the owner's own hook heard, in order."""
        heard = self.home.path / "heard.jsonl"
        return [json.loads(line)["session_id"]
                for line in (heard.read_text().splitlines() if heard.exists() else [])]

    def seats(self):
        """Every state file of a seat's: named for acme, or any seat's record or hook fact."""
        return {path.name: path.read_bytes()
                for path in (self.home.path / ".agentkit/state").iterdir()
                if "-acme." in path.name or path.name.startswith(("session-", "hook-"))}

    def rested(self):
        """Once the seat's look has read its last hook's fact: nothing of the seat's moves then."""
        state, deadline = self.home.path / ".agentkit/state", time.monotonic() + 60
        while (json.loads((state / "seat-acme.json").read_text()).get("hooked_at")
               != json.loads((state / "hook-acme.json").read_text())["at"]):
            self.assertLess(time.monotonic(), deadline, "the seat's look never read its hook")
            time.sleep(0.05)

    def test_the_seat_follows_new_s_session_and_reopens_there(self):
        record = self.record()
        self.assertEqual(record["conversation"], self.b, "the seat is not on /new's session")
        self.assertEqual([was["conversation"] for was in record["left"]], [self.a])
        # the launch's own session runs its line's Stop in the file's place
        self.assertEqual(self.heard(), [self.b], "the owner's own hook was not kept")
        done = self.home.tmux("kill-session", "-t", "=acme")
        self.assertEqual(done.code, 0, done.err)
        Terminal(self.home, "orch", "acme", size=(120, 40))
        argv = musetui.started(self.home, "acme")["argv"]
        self.assertEqual(argv[argv.index("resume") + 1], self.b, argv)

    def test_a_muse_outside_ak_fires_the_same_hook_and_moves_no_seat(self):
        self.rested()
        before = self.seats()
        # started from a shell that names the seat: only the hook's parent's word counts
        cwd = self.record()["cwd"]
        done = self.home.tmux("new-session", "-d", "-s", "notes", "-c", cwd,
                              "AGENTKIT_SESSION=acme sh -c 'env -u AGENTKIT_SESSION muse; :'")
        self.assertEqual(done.code, 0, done.err)
        # beside the seat's: the same build, telling of itself under a root of its own
        (self.home.root / "aside").mkdir()
        done = self.home.tmux("new-window", "-d", "-t", "=acme:", "-c", cwd, shlex.join([
            "env", "AGENTKIT_SESSION=acme", sys.executable, str(self.home.root / musetui.BUILD),
            str(self.home.root / "aside"), str(musetui.HERE / "muse-prompt-pane.txt")]))
        self.assertEqual(done.code, 0, done.err)
        heard = [self.b]
        for muse in ("muse", "aside/acme"):
            heard.append(musetui.started(self.home, muse)["session"])
            self.turn(muse, heard[-1])
            heard.append(str(uuid.uuid4()))     # its own `/new`
            self.turn(muse, heard[-1])
        self.assertEqual(self.heard(), heard)
        self.assertEqual(self.seats(), before)


if __name__ == "__main__":
    unittest.main()
