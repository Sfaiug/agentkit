"""A login that keeps refusing a seat's going run makes that seat `needs you`, with its remedy.

A login can pass its `auth` verb and still refuse every turn, so ak keeps each refusal in
~/.agentkit/state/login-refusals.json, per login, as the refused run's directory name, one entry
per refusal since that login last answered.  A login holding two or more is owed by each of those
runs still going, and a seat with such a run of its own reads `needs you` over its screen and its
other runs, its reason that login's remedy from its manifest.  Where more than one of its runs is
owed a login, the oldest by `finished_at` names it and dates the word.  The refusals are written
whole as ak leaves them, the runs as records under ~/.agentkit/runs; no turn and no tick runs.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and
this test fails against `/bin/false`.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

CLAUDE = "claude login expired: open it and run /login"
CODEX = ("codex login expired: open it and exit Codex, run codex login in the host shell, "
         "then reopen the session")
WAIT = "origin/main is red; retried after the next merge to origin/main"


def refused(home, **runs):
    """login-refusals.json as ak leaves it: {login: [a refused run's directory name, ...]}."""
    return home.write(".agentkit/state/login-refusals.json", json.dumps(runs, indent=2) + "\n")


def run_of(home, run_id, seat=None, **state):
    """A run's record, launched by `seat` unless it is None."""
    home.write(f".agentkit/runs/{run_id}/run.json", {
        "run_id": run_id, "title": f"Task {run_id}", "started_at": time.time() - 3 * 3600,
        **({"launched_session": seat} if seat else {}), **state})


def ak(home, *args):
    """What the program printed, once it has exited 0."""
    done = home.ak(*args, env={"COLUMNS": "200"})
    if done.code != 0:
        raise AssertionError(f"ak {' '.join(args)} exited {done.code}: {done.err}")
    return done.out


def read(home, name):
    """The seat's word as its `ak orch list` row, its `ak orch why` and its seat file give it:
    (row state, why's first line, why's reason, file word, file reason), and why's `since:`
    and the file's `word_since`."""
    header, *rows = ak(home, "orch", "list").splitlines()
    row = next(row for row in rows if row.split()[:1] == [name])
    state = row[header.index("state"):header.index("tally")].strip()
    head, *lines = ak(home, "orch", "why", name).splitlines()
    said = {key.strip(): value.strip()
            for key, _, value in (line.partition(":") for line in lines)}
    seat = json.loads((home.path / f".agentkit/state/seat-{name}.json").read_text())
    return ((state, head, said["reason"], seat.get("word"), seat.get("reason")),
            said.get("since"), seat.get("word_since"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RefusedRuns(unittest.TestCase):
    """Two seats at their prompts, each with a run of its own running; each case writes only
    the refusals, and reads each seat against how it read with none kept."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        for name in ("fix-api", "beta"):
            Seat(cls.home, name, screen="claude-prompt-pane.txt")
            run_of(cls.home, f"r-{name}", name, state="running")
        run_of(cls.home, "r-fix-api-stopped", "fix-api", state="stopped",
               finished_at=time.time() - 3600)
        for stray in ("r-stray-1", "r-stray-2"):
            run_of(cls.home, stray, state="running")
        cls.calm = {name: read(cls.home, name)[0] for name in ("fix-api", "beta")}

    def keep(self, **runs):
        self.addCleanup(refused(self.home, **runs).unlink)

    def seen(self, name):
        return read(self.home, name)[0]

    def needs_you(self, name):
        self.assertNotEqual(self.calm[name][0], "! needs you")    # the refusals' doing alone
        self.assertEqual(self.seen(name), ("! needs you", f"{name}  needs you", CLAUDE,
                                           "needs you", CLAUDE))

    def test_a_login_refusing_a_seats_run_twice_needs_you_on_that_seat_alone(self):
        self.keep(claude=["r-fix-api", "r-fix-api"])
        self.needs_you("fix-api")
        self.assertEqual(self.seen("beta"), self.calm["beta"])

    def test_two_refusals_of_one_login_are_owed_by_each_run_among_them(self):
        self.keep(claude=["r-fix-api", "r-beta"])
        self.needs_you("fix-api")
        self.needs_you("beta")

    def test_one_refusal_is_not_yet_a_login_to_fix(self):
        self.keep(claude=["r-fix-api"])
        for name in ("fix-api", "beta"):
            self.assertEqual(self.seen(name), self.calm[name])

    def test_a_run_that_has_ended_owes_no_login(self):
        self.keep(claude=["r-fix-api-stopped", "r-fix-api-stopped"])
        for name in ("fix-api", "beta"):
            self.assertEqual(self.seen(name), self.calm[name])

    def test_runs_no_seat_launched_make_no_seat_need_you(self):
        self.keep(claude=["r-stray-1", "r-stray-2"])
        for name in ("fix-api", "beta"):
            self.assertEqual(self.seen(name), self.calm[name])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OldestRun(unittest.TestCase):
    def test_the_oldest_run_owed_a_login_names_it_and_dates_the_word(self):
        home = Home()
        self.addCleanup(home.close)
        Seat(home, "fix-api", screen="claude-prompt-pane.txt")
        now = int(time.time())     # whole seconds: a build may keep no finer word_since
        older, newer = now - 2 * 3600, now - 3600
        for run_id, ended in (("r-older", older), ("r-newer", newer)):
            run_of(home, run_id, "fix-api", state="waiting", verdict="PASS", error=WAIT,
                   merge_note=WAIT, waiting_on={"ref": "origin/main"}, finished_at=ended)
        # kept before the seat is first read: only then does the word take its rung's date
        refused(home, claude=["r-newer", "r-newer"], codex=["r-older", "r-older"])
        seen, since, word_since = read(home, "fix-api")
        self.assertEqual(seen, ("! needs you", "fix-api  needs you", CODEX, "needs you", CODEX))
        self.assertTrue(since.startswith(time.strftime("%Y-%m-%d %H:%M ", time.gmtime(older))),
                        since)
        self.assertEqual(word_since, older)


class NobodyIn(unittest.TestCase):
    def test_a_seat_only_its_record_holds_needs_you_for_its_refused_run(self):
        home = Home()
        self.addCleanup(home.close)
        Seat(home, "fix-api", alive=False)
        run_of(home, "r-fix-api", "fix-api", state="running")
        refused(home, claude=["r-fix-api", "r-fix-api"])
        self.assertEqual(read(home, "fix-api")[0],
                         ("! needs you", "fix-api  needs you", CLAUDE, "needs you", CLAUDE))


if __name__ == "__main__":
    unittest.main()
