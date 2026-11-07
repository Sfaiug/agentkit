"""The tick types the week's line into the `audit` seat at its quiet prompt, once, and finishes
a line it typed before.

Each week the tick tells the `audit` seat the week's largest loss (tests/test_key_audit_seat.py).
With the seat up and at its quiet prompt, a tick types that line into it, keeps its receipt as
`typed` in state/audit.json, and once the composer reads empty marks it `delivered` and says so;
a later tick that week types nothing.  A line an earlier tick typed and died before sending is
finished from its receipt, never typed again.  A seat whose record is there and whose process is
gone is resumed on its conversation, and the line goes in on a later tick, once its harness sits
at its prompt.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
tick boxed as cron runs it, in a Home with no history.db.  Each seat's pane is
tests/fixtures/akpane.py at Claude's prompt, keeping what is typed into it; a resumed seat's is
started by a fake `claude`.  Judged by what the ticks printed, state/audit.json, what tmux holds
and what each pane received.  This test fails against `/bin/false`.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import sys
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import LOG, REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat

TOLD = "audit: told the audit seat about week {}"
CONVERSATION = "7c3e5a91-2b4d-4f6a-8e0c-1d3f5b7a9c2e"


def week():
    year, number, _ = datetime.now(timezone.utc).isocalendar()
    return f"{year}-W{number:02d}"


class Ticks:
    """A Home with the audit on and no history, the `audit` seat each case's `seated` makes,
    and two ticks over it, each seen as it ends: its run, the audit's state, what the pane took
    and the conversations `claude` was resumed on."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"], audit=True)
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        cls.weeks = {week()}
        cls.seat = cls.seated(home)
        cls.ticks = []
        for _ in range(2):
            done = home.tick()
            cls.ticks.append(SimpleNamespace(
                done=done, state=cls.audit(), typed=cls.seat.typed(),
                resumed=[argv[argv.index("--resume") + 1] for argv in home.calls("claude")
                         if "--resume" in argv]))
        cls.weeks.add(week())

    @classmethod
    def audit(cls):
        try:
            return json.loads((cls.home.path / ".agentkit/state/audit.json").read_text())
        except FileNotFoundError:
            return {}

    def told(self, tick):
        return TOLD.format(tick.state.get("week")) in tick.done.out.splitlines()

    def assertDelivered(self, tick, line):
        """By `tick`'s end `line` is entered once, its receipt kept and it is delivered."""
        self.assertEqual(tick.done.code, 0, tick.done.out + tick.done.err)
        self.assertIn(tick.state.get("week"), self.weeks)
        self.assertEqual(tick.state.get("typed"), self.seat.mark(line))
        self.assertTrue(tick.state.get("delivered"), tick.state)
        self.assertEqual(self.seat.lines(), [line])


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AtItsPrompt(Ticks, unittest.TestCase):
    @classmethod
    def seated(cls, home):
        return Seat(home, "audit")

    def test_a_tick_types_the_week_s_line_and_says_it_is_delivered(self):
        first = self.ticks[0]
        self.assertDelivered(first, first.state.get("line"))
        self.assertTrue(self.told(first), first.done.out)

    def test_a_later_tick_that_week_types_nothing_and_says_nothing(self):
        first, later = self.ticks
        self.assertEqual(later.done.code, 0, later.done.out + later.done.err)
        self.assertEqual((later.state, later.typed), (first.state, first.typed))
        self.assertFalse(self.told(later), later.done.out)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class TypedBefore(Ticks, unittest.TestCase):
    @classmethod
    def seated(cls, home):
        """A seat busy while an earlier tick writes the week's line, which that tick then typed
        once the seat came to its prompt, and died before its Enter: the line in the composer
        and its receipt kept."""
        seat = Seat(home, "audit", screen="claude-working-pane.txt")
        done = home.tick()
        state = cls.audit()
        cls.line = state.get("line")
        assert done.code == 0 and cls.line and not seat.typed(), done.out + done.err
        assert home.tmux("send-keys", "-t", seat.pane, "-l", cls.line).code == 0
        deadline = time.monotonic() + 30
        while seat.typed() != cls.line:
            assert time.monotonic() < deadline, seat.typed()
            time.sleep(0.05)
        seat.show("claude-prompt-pane.txt")
        home.write(".agentkit/state/audit.json", {**state, "typed": seat.mark(cls.line)})
        return seat

    def test_it_is_finished_from_its_receipt_and_never_typed_again(self):
        self.assertEqual([tick.done.code for tick in self.ticks], [0, 0])
        self.assertDelivered(self.ticks[-1], self.line)
        self.assertEqual(self.seat.typed().count(self.line), 1, self.seat.typed())
        self.assertEqual([self.told(tick) for tick in self.ticks].count(True), 1)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class Resumed(Ticks, unittest.TestCase):
    @classmethod
    def seated(cls, home):
        """A seat's record whose process is gone, its conversation opened in Claude's store;
        `claude` logs what it was started with and sits at Claude's prompt."""
        # A session of the owner's own keeps ak's tmux server up outside the box: the seat a
        # tick resumes is still there for the next tick.
        done = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", "notes", "sleep 3600")
        assert done.code == 0, done.err
        seat = Seat(home, "audit", alive=False, record={"conversation": CONVERSATION})
        # Claude files a workspace's conversations under its path, each character that is not
        # a letter or a digit a dash.
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl",
                   '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        log = LOG.format(python=shlex.quote(sys.executable),
                         log=shlex.quote(str(home.log("claude"))))
        home.fake("claude", log + "exec " + shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]) + "\n")
        return seat

    def test_a_tick_resumes_it_on_its_conversation_and_types_nothing_yet(self):
        first = self.ticks[0]
        self.assertEqual(first.done.code, 0, first.done.out + first.done.err)
        self.assertEqual(first.resumed, [CONVERSATION])
        self.assertEqual(first.typed, "")
        self.assertFalse(first.state.get("delivered"), first.state)
        self.assertFalse(self.told(first), first.done.out)

    def test_the_line_goes_in_on_a_later_tick_once_the_harness_sits_at_its_prompt(self):
        later = self.ticks[1]
        self.assertEqual(later.resumed, [CONVERSATION])
        self.assertDelivered(later, later.state.get("line"))
        self.assertTrue(self.told(later), later.done.out)


if __name__ == "__main__":
    unittest.main()
