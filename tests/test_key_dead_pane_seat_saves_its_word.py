"""`ak orch list` and `ak orch why` save the word they print for a seat whose panes all died.

ak's seats run under `remain-on-exit`, so a harness that quits leaves its session behind with its
panes dead.  Either command decides such a seat's word as it prints it, and leaves that word and
its reason in the seat's file and on its tmux bar, as a client attached to the seat draws it: line
one names the word, and under a `needs you` line two says why.  `DeadPaneSeatSavesItsWord` takes
each state that decides such a seat's word, one at a time, and `LoggedOutOverADeadPaneSeat` a
login no harness owns over two of them.  Each command meets the state in a Home of its own, so
neither finds the other's write.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, beside a seat of tests/fixtures/akseat.py whose harness the test kills,
and the bar is read off a terminal of tests/fixtures/akterm.py; this test fails against
`/bin/false`.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home, owner
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

CLOSED = "session closed: press 1 to reopen"
GH = "GitHub is logged out: run `gh auth login -p https -w`"
CHIPS = {"needs you": "! needs you", "working": "● working", "idle": "○ idle"}
RUN = "20261106-0900-fix-api"
TOKEN = "claude_oauth_token"     # the worker token claude's manifest declares, and its remedy
REMEDY = "run claude setup-token and replace ~/.agentkit/secrets/claude_oauth_token"
LAUNCH = "5d1e8a3c7b9f4e2a8c6d0b1f3e5a7c9d"     # a Codex launch's receipt token
DAY = 86400


def died(home, seat):
    """End the seat's harness, as one that quit, and wait for tmux to hold its pane dead."""
    pane = ("display-message", "-p", "-t", seat.pane)
    os.kill(int(home.tmux(*pane, "#{pane_pid}").out), signal.SIGKILL)
    deadline = time.monotonic() + 30
    while home.tmux(*pane, "#{pane_dead}").out.strip() != "1":
        assert time.monotonic() < deadline, "the pane never died"
        time.sleep(0.05)


def bar(home):
    """The bar's two lines as a client attached to the seat draws them, at the foot of a
    terminal wide enough for the longest reason.  Read once the client has drawn and its frame
    has held still for a second, never once it shows the word: a bar left blank then fails at
    once, rather than when a wait for its word runs out."""
    seen = Terminal(home, "-L", SOCKET, "attach", "-r", "-t", "=acme:", size=(160, 10),
                    program=REAL_TMUX)
    shown, since, deadline = None, time.monotonic(), time.monotonic() + 30
    while True:
        screen = seen.screen()
        if screen != shown:
            shown, since = screen, time.monotonic()
        elif shown.strip() and time.monotonic() - since >= 1 or time.monotonic() > deadline:
            return shown.splitlines()[-2:]
        time.sleep(0.05)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Saved(unittest.TestCase):
    """Each state as what keeps it leaves it on disk, and `holds`, the check both commands meet."""

    def holds(self, word, reason, *states, **seat):
        """Each command, run once the seat (`seat` its Seat arguments) has died and `states` are
        written, prints `word` and `reason` and leaves both in the seat's file and on its bar."""
        for command in (("orch", "list"), ("orch", "why", "acme")):
            with self.subTest(command[1]), Home() as home:
                died(home, Seat(home, "acme", **seat))
                for state in states:
                    state(home)
                done = home.ak(*command)
                self.assertEqual(done.code, 0, done.err)
                lines = done.out.splitlines()
                if command[1] == "why":
                    self.assertEqual(lines[:2], [f"acme  {word}", f"  reason:    {reason}"],
                                     done.out)
                else:
                    rows = {line.split()[0]: line for line in lines if line.strip()}
                    self.assertIn(CHIPS[word], rows.get("acme", ""), done.out)
                file = home.path / ".agentkit/state/seat-acme.json"
                saved = json.loads(file.read_text()) if file.exists() else {}
                self.assertEqual((saved.get("word"), saved.get("reason")), (word, reason))
                one, two = bar(home)
                self.assertIn(CHIPS[word], one)
                # line two carries the reason only under `needs you`; any other word's names
                # the seat's crew
                if word == "needs you":
                    self.assertIn(reason, two)

    def question(self, home):
        """A question it asked with `ak notify needs` that nothing has answered."""
        home.write(".agentkit/state/notify-acme.json",
                   {"session": "acme", "kind": "needs", "text": "Which database should the "
                    "API use?", "time": time.time() - 60})

    def failed_hook(self, home):
        """Its last turn ended on Claude's StopFailure, as its hook wrote it down."""
        home.write(".agentkit/state/hook-acme.json",
                   {"session": "acme", "event": "StopFailure", "kind": "", "text": "",
                    "at": time.time() - 60})

    def owed_line(self, home):
        """A line ak owes it, to type at its next quiet prompt."""
        home.write(".agentkit/state/seat-acme.json", {"owed_lines": [
            {"line": f"Run {RUN} passed and merged.", "id": "4f2a9c1e7b3d5a80"}]})

    def wait(self, home):
        """Its own `ak wait` on a pull request nothing has found over yet."""
        home.write(".agentkit/state/seat-acme.json",
                   {"wait": {"kind": "pr", "on": "acme/api#7", "at": time.time() - 60}})

    def ran(self, home, **fields):
        """The record of a run the seat launched, `fields` over it."""
        home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "Fix the API", "launched_session": "acme",
            "repo": str(home.path / "code" / "acme"), "started_at": time.time() - 600, **fields})

    def going(self, home):
        """A run of its own in its executor step, its loop alive."""
        loop = subprocess.Popen(["sleep", "3600"])
        self.addCleanup(loop.wait)
        self.addCleanup(loop.kill)
        self.ran(home, state="running", verdict=None, merged=False, step="executor",
                 finished_at=None, **owner(loop.pid))

    def merged(self, home):
        """A run of its own merged two minutes back, its project yet to prove itself live."""
        self.ran(home, state="pass", verdict="PASS", merged=True, finished_at=time.time() - 120,
                 health={"command": "curl -fsS https://acme.example/health"})

    def receipt(self, home):
        """The receipt of its Codex launch, whose thread never reported back."""
        home.write(f".agentkit/state/codex-launch-{LAUNCH}.json",
                   {"launch": LAUNCH, "cwd": str(home.path / "code" / "acme"), "expected": None,
                    "remote": "9b7c5a3e1f2d4c6b8a0e2f4d6c8b0a1e"})

    def gh_out(self, home):
        """The tick found gh logged out."""
        home.write(".agentkit/state/watch.json", {"gh_out": {"at": time.time() - 300}})

    def token_expired(self, home):
        """The tick found claude's worker token a year and a day old."""
        token = home.write(f".agentkit/secrets/{TOKEN}", "acme-token\n", ago=366 * DAY)
        home.write(".agentkit/state/watch.json", {"worker_tokens": {"claude": {
            "harness": "claude", "remedy": REMEDY, "at": time.time() - 60,
            "checked_at": time.time() - 60, "mtime": token.stat().st_mtime, "days": None,
            "expired": True, "why": "claude worker token expired"}}})


class DeadPaneSeatSavesItsWord(Saved):
    def test_a_question_standing_for_it_needs_you_to_reopen_it(self):
        self.holds("needs you", CLOSED, self.question)

    def test_its_last_turns_hook_failed_and_it_rests(self):
        self.holds("idle", CLOSED, self.failed_hook)

    def test_a_line_owed_to_it_and_it_rests(self):
        self.holds("idle", CLOSED, self.owed_line)

    def test_a_wait_of_its_own_unfinished_keeps_it_working(self):
        self.holds("working", "waiting on acme/api#7", self.wait)

    def test_a_run_of_its_own_going_keeps_it_working(self):
        self.holds("working", "1 running · Fix the API", self.going)

    def test_a_run_of_its_own_merged_its_live_check_pending_keeps_it_working(self):
        self.holds("working", "waiting on the live check · Fix the API", self.merged)

    def test_its_harnesss_launch_receipt_in_its_record_rests_and_starts_fresh(self):
        self.holds("idle", f"{CLOSED} · starts a new Codex conversation", self.receipt,
                   model="astra", screen="codex-prompt-pane.txt", composer="›",
                   record={"codex_launch": LAUNCH, "conversation": None, "id_source": None,
                           "resumable": False})


class LoggedOutOverADeadPaneSeat(Saved):
    def test_github_logged_out_needs_you_over_a_question_and_a_run(self):
        for state in (self.question, self.going):
            with self.subTest(state.__name__):
                self.holds("needs you", GH, state, self.gh_out)

    def test_a_worker_token_expired_needs_you_over_a_question_and_a_run(self):
        for state in (self.question, self.going):
            with self.subTest(state.__name__):
                self.holds("needs you", f"claude worker token expired: {REMEDY}", state,
                           self.token_expired)


if __name__ == "__main__":
    unittest.main()
