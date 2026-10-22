"""`ak orch list` lists seats only: a hand-made tmux session running no agent is none, and a seat
left on the default tmux server from before ak had a server of its own is listed as `legacy`.

ak's own server holds whatever a person or a model opens there by hand, a shell or a watcher
loop, and a row for each would put nobody's session on every screen; the default server is the
owner's own, and only ak's `@ak_orch` mark brings a session there onto ak's screens.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, the sessions are
made on the Home's own tmux servers, and ak is judged by what it prints.
"""

import re
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akseat import FIXTURES, PANE, Seat

DEFAULT = "default"   # tmux's own server, the one a bare `tmux` reaches
NONE = "no orchestrator session; `ak orch <name>` starts one"


def no_seat(name):
    return f"ak orch: no orchestrator session '{name}'; `ak orch list` shows them\n"


def by_hand(home, name, *command, server=SOCKET, mark=False):
    """A session someone opened with `tmux new`, running that command or a shell; `mark` gives
    it the mark ak's own launch sets."""
    done = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", name, "-x", "100",
                     "-y", "30", "-c", str(home.path), *command, server=server)
    assert done.code == 0, done.err
    if mark:
        done = home.tmux("set-option", "-t", f"={name}:", "@ak_orch", "1", server=server)
        assert done.code == 0, done.err


def harness(home):
    """A command whose process goes by the name of a harness ak runs, as one started by hand."""
    path = home.root / "agents" / "claude"
    path.parent.mkdir(exist_ok=True)
    path.write_text("import time\ntime.sleep(86400)\n")
    return sys.executable, str(path)


def rows(out, name):
    """The listing's rows for that seat."""
    return [line for line in out.splitlines() if line.split(" ", 1)[0] == name]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AgentlessSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        by_hand(cls.home, "scratch")

    def test_a_hand_made_session_running_no_agent_is_not_listed(self):
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines()[0], NONE)

    def test_asking_why_about_it_says_there_is_no_such_seat(self):
        done = self.home.ak("orch", "why", "scratch")
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.err, no_seat("scratch"))

    def test_the_same_session_running_a_harness_is_a_seat_with_no_models(self):
        # What decides is the agent in the pane: without this, a test of the skip alone holds
        # for a build that lists no hand-made session at all.
        with Home() as home:
            by_hand(home, "scratch")
            by_hand(home, "acme", *harness(home))
            done = home.ak("orch", "list")
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(rows(done.out, "scratch"), [])
            [row] = rows(done.out, "acme")
            self.assertRegex(row, r"\s\?\s+\?\s")
            self.assertFalse(row.endswith("legacy"), row)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LegacySeat(unittest.TestCase):
    """acme is a seat from before ak had its own server, showing a turn at work, with no record
    of ak's; notes is the owner's own session there, a harness in it; beta is on both."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        screen = home.root / "acme.txt"
        screen.write_text((FIXTURES / "claude-working-pane.txt").read_text())
        by_hand(home, "acme", shlex.join([sys.executable, str(PANE), str(screen),
                                          str(home.root / "acme.typed")]),
                server=DEFAULT, mark=True)
        deadline = time.monotonic() + 30
        while "esc to interrupt" not in home.tmux("capture-pane", "-p", "-t", "=acme:",
                                                  server=DEFAULT).out:
            assert time.monotonic() < deadline, "acme never showed its screen"
            time.sleep(0.05)
        by_hand(home, "notes", *harness(home), server=DEFAULT)
        Seat(home, "beta")
        by_hand(home, "beta", server=DEFAULT, mark=True)
        cls.listed = home.ak("orch", "list")
        assert cls.listed.code == 0, cls.listed.err

    def test_a_marked_session_on_the_default_server_is_listed_as_legacy(self):
        [row] = rows(self.listed.out, "acme")
        self.assertRegex(row, r"^acme\s.*○ idle\s.*\s\?\s+\?\s.*\slegacy$")

    def test_with_no_record_its_screen_is_not_read_and_it_reads_idle(self):
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        self.assertEqual(lines[0], "acme  idle")
        self.assertIn("  authority: default  rule: -", lines)

    def test_the_owners_own_sessions_there_are_not_listed_even_running_a_harness(self):
        self.assertEqual(rows(self.listed.out, "notes"), [])
        done = self.home.ak("orch", "why", "notes")
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.err, no_seat("notes"))

    def test_a_name_on_both_servers_is_listed_once_from_aks_own(self):
        [row] = rows(self.listed.out, "beta")
        self.assertFalse(row.endswith("legacy"), row)


if __name__ == "__main__":
    unittest.main()
