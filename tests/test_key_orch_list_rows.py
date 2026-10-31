"""`ak orch list`: one row per seat, its word and its run tally in fixed columns.

The list is the plain-text view of every seat: a model or a person reads which seat needs them
from it, and the seat's own status bar gets the same word as the list is drawn.  The word is one
of four (working, needs you, done, idle) and follows what the seat shows, a question it sent and
the runs it launched; the tally counts those runs.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py among seats from tests/fixtures/akseat.py, and the
bar is read from a client attached to the seat, as a person in the seat sees it.
"""

import json
import re
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat

HEADER = ["name", "project", "state", "tally", "orchestrator", "workers", "age"]
NO_SLICE = "no slice (no user systemd manager)"   # a Home has no user systemd manager
AGE = re.compile(r"<1m|[1-9][0-9]*[mhd]")
WIDE = {"COLUMNS": "200"}


def listed(home, width=WIDE):
    """`ak orch list`'s lines, once it has exited 0."""
    done = home.ak("orch", "list", env=width)
    if done.code != 0:
        raise AssertionError(f"ak orch list exited {done.code}: {done.err}")
    return done.out.splitlines()


def fields(test, header, row):
    """The row cut where the header's words start; each field must start right there, so a
    column that drifts from its header fails."""
    starts = [match.start() for match in re.finditer(r"\S+", header)]
    found = []
    for at, end in zip(starts, starts[1:] + [None]):
        test.assertTrue(row[at:at + 1].strip() and row[at - 1:at] in ("", " "),
                        f"no field starts under column {at}:\n{header}\n{row}")
        found.append(row[at:end].strip())
    return found


def bar(home, seat, bound=30):
    """The rows under the seat's screen as a person attached to it sees them, once they show a
    word; a client of the seat's size and two rows more, so the seat's pane keeps its size."""
    size = home.tmux("display-message", "-p", "-t", seat.pane, "#{window_width} #{window_height}")
    width, height = map(int, size.out.split())
    attach = shlex.join(["env", "-u", "TMUX", "-u", "TMUX_PANE", REAL_TMUX, "-L", SOCKET,
                         "attach", "-t", f"={seat.name}"])
    # The viewer server outlives each client, so the next one never meets it on its way out
    # ("server exited unexpectedly"); the Home's close ends it.
    done = home.tmux("-f", "/dev/null", "new-session", "-d", "-x", str(width), "-y",
                     str(height + 2), "-P", "-F", "#{pane_id}", attach, ";",
                     "set", "-s", "exit-empty", "off", server="viewer")
    assert done.code == 0, done.err
    pane = done.out.strip()
    try:
        deadline = time.monotonic() + bound
        while True:
            rows = home.tmux("capture-pane", "-p", "-t", pane, server="viewer").out
            under = " ".join(" ".join(rows.split("\n")[height:]).split())
            if any(word in under for word in ("idle", "needs you", "working", "done")):
                return under
            if time.monotonic() > deadline:
                return under
            time.sleep(0.05)
    finally:
        home.tmux("kill-session", "-t", pane, server="viewer")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ALiveSeat(unittest.TestCase):
    """One seat on ak's tmux, its screen at the prompt; each case puts back what it changed."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.seat = Seat(cls.home, "fix-api", screen="claude-prompt-pane.txt",
                        record={"workers": ["opus", "astra"]})
        cls.state = cls.home.path / ".agentkit" / "state"

    def row(self):
        """The seat's fields under the exact header, and the slice line closing the list."""
        lines = listed(self.home)
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[0].split(), HEADER)
        self.assertEqual(lines[2], NO_SLICE)
        return fields(self, lines[0], lines[1])

    def why(self):
        done = self.home.ak("orch", "why", "fix-api", env=WIDE)
        self.assertEqual(done.code, 0, done.err)
        return done.out.splitlines()

    def test_an_idle_seat_is_one_row_with_its_project_word_tally_models_and_age(self):
        lines = listed(self.home)
        self.assertEqual(lines[0], "name     project     state   tally        orchestrator  "
                                   "workers     age")
        self.assertRegex(lines[1], r"^fix-api  no project  ○ idle  no runs yet  opus          "
                                   r"opus,astra  (" + AGE.pattern + ")$")
        self.assertEqual(lines[2:], [NO_SLICE])
        # the word the list read is the seat's, for every other screen to read
        seat = json.loads((self.state / "seat-fix-api.json").read_text())
        self.assertEqual(seat["word"], "idle")

    def test_the_list_puts_the_word_on_the_seats_own_bar(self):
        listed(self.home)
        under = bar(self.home, self.seat)
        self.assertIn("○ idle", under)
        self.assertIn("fix-api", under)

    def test_a_question_the_seat_sent_reads_needs_you_with_the_question_as_reason(self):
        notice = self.home.write(".agentkit/state/notify-fix-api.json",
                                 {"session": "fix-api", "kind": "needs",
                                  "text": "Which branch?", "time": time.time()})
        self.addCleanup(notice.unlink, missing_ok=True)
        self.assertEqual(self.row()[2:4], ["! needs you", "no runs yet"])
        self.assertEqual(self.why()[:2], ["fix-api  needs you", "  reason:    Which branch?"])

    def test_a_run_the_seat_launched_reads_working_and_counts_in_the_tally(self):
        run = self.home.write(".agentkit/runs/r-fix-api/run.json",
                              {"run_id": "r-fix-api", "state": "running",
                               "launched_session": "fix-api", "title": "Fix api"})
        self.addCleanup(run.unlink, missing_ok=True)
        self.assertEqual(self.row()[2:4], ["● working", "1 running · 0 merged"])
        self.assertEqual(self.why()[:2], ["fix-api  working", "  reason:    1 running · Fix api"])

    def test_a_question_on_the_seats_screen_reads_needs_you(self):
        self.seat.show("claude-question-pane.txt")
        self.addCleanup(self.seat.show, "claude-prompt-pane.txt")
        found = self.row()
        self.assertEqual(found[:6], ["fix-api", "no project", "! needs you", "no runs yet",
                                     "opus", "opus,astra"])
        self.assertRegex(found[6], AGE)


class SeatsOnlyTheirRecordsHold(unittest.TestCase):
    """Seats tmux no longer holds keep their rows, aged from their records."""

    def test_each_seat_is_a_row_in_columns_aligned_under_the_header(self):
        made = int(time.time()) - 90 * 60
        with Home() as home:
            Seat(home, "atoll", model="fable", alive=False,
                 record={"workers": ["fable", "astra"], "created": made,
                         "repo": str(home.path / "code" / "atoll")})
            Seat(home, "scribe", model="astra", alive=False, record={"created": made})
            for run, extra in (("r-going", {"state": "running"}),
                               ("r-merged", {"state": "pass", "merged": True,
                                             "started_at": time.time() - 1200,
                                             "finished_at": time.time() - 600})):
                home.write(f".agentkit/runs/{run}/run.json",
                           {"run_id": run, "launched_session": "atoll", "title": "Beta",
                            "repo": str(home.path / "code" / "atoll"), **extra})
            lines = listed(home, {"COLUMNS": "100"})
        self.assertEqual(lines, [
            "name    project     state      tally                 orchestrator  workers      age",
            "atoll   atoll       ● working  1 running · 1 merged  fable         fable,astra  1h",
            "scribe  no project  ○ idle     no runs yet           astra         astra        1h",
            NO_SLICE])


if __name__ == "__main__":
    unittest.main()
