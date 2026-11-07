"""A typed line's mark names the process of the pane it went into: a harness started there since
gets the line again, and the one it went into is never typed into twice.

The tick tells the `audit` seat the week's line (tests/test_key_audit_line_delivered.py) and keeps
the mark of the line it typed as `typed` in state/audit.json until the seat's composer reads
empty, when the line is `delivered`.  The mark names the seat by its tmux birth, which is in
whole seconds and which a pane respawned in place keeps, and by its pane's process, which a
harness started since does not share.  With a line's mark kept and the seat's composer empty:

- a pane respawned since the line was typed gets it again, with its Enter, and only then is the
  line delivered, its mark naming the new process;
- a pane respawned after the tick asks tmux its process, as a launch holding the seat's send
  lock does while the tick waits for it, is not taken for the line delivered: nothing is typed
  and the line is not delivered, and the next tick types it, with its Enter, and delivers it;
- a pane whose process is the one its mark names is typed nothing, and the line is delivered.

Black-box, as tests/test_key_audit_line_delivered.py is: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, each tick boxed as cron runs it, in a Home with no
history.db, and the seat's pane is tests/fixtures/akpane.py, keeping what is typed into it.
Judged by what the tick printed, state/audit.json and what the pane received.  This test fails
against `/bin/false`.
"""

import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, SOCKET, Home, boxable
from fixtures.akseat import PANE, Seat

TOLD = "audit: told the audit seat about week {}"


class Marked:
    """A Home with the audit on and no history; its seat busy while a tick writes the week's
    line, whose mark is then kept as a tick that typed it and died before its delivery leaves
    it; what each case's `since` does to the pane; the seat at its prompt, its composer empty;
    and one tick over it, seen as it ends."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"], audit=True)
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        cls.seat = seat = Seat(home, "audit", screen="claude-working-pane.txt")
        done = home.tick()
        state = cls.audit()
        cls.line = state.get("line")
        assert done.code == 0 and cls.line and not seat.typed(), done.out + done.err
        cls.typed = seat.mark(cls.line)
        home.write(".agentkit/state/audit.json", {**state, "typed": cls.typed})
        cls.since(home, seat)
        seat.show("claude-prompt-pane.txt")
        cls.done = home.tick()
        cls.state = cls.audit()

    @classmethod
    def audit(cls):
        return json.loads((cls.home.path / ".agentkit/state/audit.json").read_text())

    def assertToldOnce(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertTrue(self.state.get("delivered"), self.state)
        self.assertIn(TOLD.format(self.state.get("week")), self.done.out.splitlines())


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class Respawned(Marked, unittest.TestCase):
    @classmethod
    def since(cls, home, seat):
        """Its harness started again in place: the same pane and birth, another process."""
        done = home.tmux("respawn-pane", "-k", "-t", seat.pane, sys.executable, str(PANE),
                         str(seat.screen_file), str(seat.typed_file), seat.composer)
        assert done.code == 0, done.err
        now = seat.mark(cls.line)
        assert now["seat"] == cls.typed["seat"] and now["pid"] != cls.typed["pid"], now

    def test_the_line_is_typed_again_with_its_enter_and_then_delivered(self):
        self.assertToldOnce()
        self.assertEqual(self.seat.lines(), [self.line])
        self.assertEqual(self.state.get("typed"), self.seat.mark(self.line))


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class RespawnedAfterItsPin(Marked, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.first, cls.first_typed = (cls.done, cls.state), cls.seat.typed()
        cls.done = cls.home.tick()
        cls.state = cls.audit()

    @classmethod
    def since(cls, home, seat):
        """Its harness started again in place, once, right after the tick's first ask of the
        pane's process has its answer, and drawn before the tick goes on: the title its frame
        sets says so."""
        q = shlex.quote
        shim = home.root / "tmux-shim"
        (home.bin / "tmux").replace(shim)
        armed = home.root / "respawn-armed"
        armed.touch()
        tmux = shlex.join([str(shim), "-L", SOCKET])
        harness = shlex.join([sys.executable, str(PANE), str(seat.screen_file),
                              str(seat.typed_file), seat.composer])
        home.fake("tmux", f"""#!/bin/sh
{q(str(shim))} "$@"; said=$?
case "$*" in
  *display-message*'#{{pane_pid}}'*)
    if rm {q(str(armed))} 2>/dev/null; then
      {tmux} select-pane -t {q(seat.pane)} -T respawned
      {tmux} respawn-pane -k -t {q(seat.pane)} {q(harness)}
      tries=600
      while [ "$({tmux} display-message -p -t {q(seat.pane)} '#{{pane_title}}')" = respawned ] \
          && [ $((tries -= 1)) -gt 0 ]; do sleep 0.05; done
    fi ;;
esac
exit $said
""")

    def test_the_old_mark_delivers_nothing_and_the_next_tick_types_the_line(self):
        done, state = self.first
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertFalse((self.home.root / "respawn-armed").exists(), "the pane was not respawned")
        self.assertFalse(state.get("delivered"), state)
        self.assertEqual(self.first_typed, "")
        self.assertToldOnce()
        self.assertEqual(self.seat.lines(), [self.line])
        now = self.seat.mark(self.line)
        self.assertNotEqual(now["pid"], self.typed["pid"])
        self.assertEqual(self.state.get("typed"), now)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class LivesOn(Marked, unittest.TestCase):
    @classmethod
    def since(cls, home, seat):
        """Nothing: the harness the line went into took it, and runs on."""

    def test_the_line_is_delivered_and_nothing_is_typed(self):
        self.assertToldOnce()
        self.assertEqual(self.seat.typed(), "")
        self.assertEqual(self.state.get("typed"), self.typed)


if __name__ == "__main__":
    unittest.main()
