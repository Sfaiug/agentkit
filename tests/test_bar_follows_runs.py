"""A run's step, round and ending rewrite its seat's status bar at once, through the one writer.

Not three minutes later at the next tick: every step a run enters (a new round enters its
executor step again) and every ending rewrites the bar of the seat that launched it, through
`watch.announce_state`, without looking at the seat's screen.  A job on the seats' tmux server
does the writing, so a writer that is busy holds up neither the run nor its exit, and the bar
still lands after the command that started it is gone.  A run without a seat, a legacy seat and
a seat tmux has lost get nothing written.  Offline: a temporary HOME and a fake tmux on PATH.
"""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
# The redraw reads ~/.agentkit from HOME and finds tmux on PATH in a job of its own, so both
# are set before agentkit is imported: the test, the run and the redraw see one world.
SANDBOX = tempfile.TemporaryDirectory(prefix=".ak-test-bar-follows-runs-", dir=REPO)
HOME = Path(SANDBOX.name)
os.environ.update(HOME=str(HOME), PATH=f"{HOME / 'bin'}{os.pathsep}{os.environ['PATH']}",
                  AGENTKIT_TMUX_SOCKET="agentkit-test", AK_RUN_DEPTH="0", AK_MAX_RUNS="0")
for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_SESSION", "TMUX"):
    os.environ.pop(key, None)
sys.path.insert(0, str(REPO))
from agentkit import config, orch, record, run, watch

# Answers list-sessions and list-panes as tmux 3.5a does, from the seats each server holds
# (`own`, `legacy`), and writes down every command it is given.  `run-shell -b -t =seat:` is
# refused for a seat the server does not hold, and otherwise runs in the background, the job
# counted in `jobs` and, once done, in `jobs-done`.
TMUX = """#!/bin/bash
socket=
[[ $1 = -L ]] && { socket=$2; shift 2; }
printf '%s\\t' "$socket" "$@" >>"$HOME/tmux-calls"; printf '\\n' >>"$HOME/tmux-calls"
seats="$HOME/legacy"; [[ $socket = agentkit-test ]] && seats="$HOME/own"
case $1 in
  list-sessions) while read -r name; do printf '%s\\t%s\\t1\\t0\\t1\\n' "$name" "$HOME"; done <"$seats" ;;
  list-panes) while read -r name; do printf '%s\\t0\\n' "$name"; done <"$seats" ;;
  run-shell) [[ -e "$HOME/tmux-stall" ]] && exec python3 -c 'import signal; signal.pause()'
             target=${4#=}; target=${target%:}
             grep -qxF -- "$target" "$seats" || { echo "can't find session: $target"; exit 1; }
             echo >>"$HOME/jobs"
             ( sh -c "${5//##/#}"; echo >>"$HOME/jobs-done" ) </dev/null >/dev/null 2>&1 & ;;
esac
exit 0
"""

# A run's own process: it enters a step, then exits.
STEP = """
import sys, types
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from agentkit import record, run
run_dir = Path(sys.argv[2])
state = record.read_state(run_dir)
run.Loop.step(types.SimpleNamespace(state=state, log=print,
                                    save=lambda: record.save_state(run_dir, state)), "merge")
"""
CALLER = STEP + '\nrun.mark_state(run_dir, "error", error="the api is down")\n'


class BarFollowsRuns(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(config.HOME, ignore_errors=True)
        config.ensure_dirs()
        (HOME / "bin").mkdir(exist_ok=True)
        (HOME / "bin" / "tmux").write_text(TMUX)
        (HOME / "bin" / "tmux").chmod(0o755)
        self.seats(own=("acme", "fix-api"))
        self.calls = HOME / "tmux-calls"
        for name in ("tmux-calls", "jobs", "jobs-done"):
            (HOME / name).write_text("")
        config.save_session(config.load(), "acme", "fable", ["opus"],
                            {"repo": str(HOME), "cwd": str(HOME)})
        self.run_dir = config.RUNS / "20261002-1400-fix-api"
        self.run_dir.mkdir(parents=True)
        self.state = {"run_id": self.run_dir.name, "title": "Fix the api", "state": "running",
                      "verdict": None, "launched_session": "acme", "executor": "opus",
                      "reviewer": "astra", "rounds": 3, "round_summaries": [], "started_at": 1}
        record.save_state(self.run_dir, self.state)
        self.loop = types.SimpleNamespace(
            state=self.state, log=lambda *_a, **_kw: None,
            save=lambda: record.save_state(self.run_dir, self.state))

    def seats(self, own=(), legacy=()):
        (HOME / "own").write_text("".join(f"{name}\n" for name in own))
        (HOME / "legacy").write_text("".join(f"{name}\n" for name in legacy))

    def settle(self):
        """Wait for every redraw job tmux was given, so the bar is read once they have finished."""
        deadline = time.monotonic() + 30
        while ((HOME / "jobs").read_text() != (HOME / "jobs-done").read_text()
               and time.monotonic() < deadline):
            time.sleep(0.05)

    def bars(self, name="acme"):
        """The status-left writes that seat's bar got on agentkit's own server."""
        rows = [line.split("\t") for line in self.calls.read_text().splitlines()]
        return [row[5] for row in rows
                if row[:5] == ["agentkit-test", "set-option", "-t", name, "status-left"]]

    def step(self, name):
        run.Loop.step(self.loop, name)
        self.settle()

    def test_every_step_and_the_ending_rewrite_the_launching_seats_bar_without_a_look(self):
        for count, name in enumerate(("executor", "done-when", "reviewer", "executor", "merge"), 1):
            if count == 4:    # round two begins with its executor step again
                self.state["round_summaries"].append({"round": 1, "summary": "fixed"})
            self.step(name)
            self.assertEqual(record.read_state(self.run_dir)["step"], name)
            self.assertEqual(len(self.bars()), count)
        self.assertIn("working", self.bars()[-1])
        run.mark_state(self.run_dir, "error", error="the api is down")
        self.settle()
        self.assertEqual(len(self.bars()), 6)
        self.assertEqual(self.bars("fix-api"), [])
        self.assertNotIn("capture-pane", self.calls.read_text())

    def test_nothing_is_written_without_a_live_seat_of_ours(self):
        cases = {"no seat": (None, ("acme",), ()),
                 "legacy seat": ("acme", (), ("acme",)),
                 "seat tmux lost": ("acme", (), ())}
        for case, (launched, own, legacy) in cases.items():
            with self.subTest(case):
                self.calls.write_text("")
                self.state["launched_session"] = launched
                self.seats(own, legacy)
                self.step("reviewer")
                self.assertNotIn("set-option", self.calls.read_text())
                self.assertEqual((HOME / "jobs").read_text(), "")
                self.assertEqual(record.read_state(self.run_dir)["step"], "reviewer")

    def test_a_busy_writer_holds_up_neither_the_run_nor_its_exit(self):
        with watch.announcing("acme"):     # a menu, the tick or the seat's hook publishing it
            subprocess.run([sys.executable, "-c", CALLER, str(REPO), str(self.run_dir)],
                           check=True, timeout=20, capture_output=True)
            self.assertEqual(record.read_state(self.run_dir)["state"], "error")
            self.assertEqual(self.bars(), [])
        # the run has exited; the step's and the ending's redraws still land
        deadline = time.monotonic() + 30
        while len(self.bars()) < 2 and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(len(self.bars()), 2)

    def test_a_tmux_that_fails_never_reaches_the_run(self):
        with patch.object(orch, "tmux_out", side_effect=OSError("no tmux")):
            self.step("done-when")
        self.assertEqual(record.read_state(self.run_dir)["step"], "done-when")

    def test_an_unresponsive_tmux_never_stops_the_run_and_the_next_step_redraws(self):
        stall = HOME / "tmux-stall"
        stall.touch()
        try:
            with subprocess.Popen([sys.executable, "-c", STEP, str(REPO), str(self.run_dir)],
                                  start_new_session=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as caller:
                try:
                    _, err = caller.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    # A broken handoff leaves the fake tmux stuck too: kill only this probe's
                    # group before reaping its leader, so a failed test leaves no process behind.
                    os.killpg(caller.pid, signal.SIGKILL)
                    self.fail("Loop.step never returned while tmux did not answer")
                self.assertEqual(caller.returncode, 0, err)
        finally:
            stall.unlink()
        self.assertEqual(record.read_state(self.run_dir)["step"], "merge")
        self.assertIn("run-shell\t-b\t-t\t=acme:", self.calls.read_text())
        self.assertEqual(self.bars(), [])
        self.step("reviewer")
        self.assertEqual(len(self.bars()), 1)


if __name__ == "__main__":
    unittest.main()
