"""Check d2 of the fresh-install gate passes on a seat Stop closed and fails on one it left going.

A seat the owner stops stays listed, `idle` and closed by the owner.  Offline: d2's own block
of tests/e2e-fresh.sh, its pty drive and `as` faked, fed what the real `ak orch why` prints
for a fake seat: one stopped the way `ak orch stop` stops it, one still working.
"""

from contextlib import redirect_stdout
import io
import os
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch, usage, watch, worker
from agentkit import record

FRESH = (REPO / "tests/e2e-fresh.sh").read_text()
D2 = FRESH[FRESH.index("# ==== d, closing:"):FRESH.index("# ==== h)")]

# Stand-ins for the gate's helpers: the pty drive went through, `as` answers with
# the listing under test, the wait for the stop takes no time, and the verdict is the exit code.
FAKES = r'''
doing() { true; }
drive() { true; }
as() { cat "$LISTING"; }
sleep() { true; }
bad=""
must() { local what=$1; shift; "$@" || bad="$bad; $what"; }
verdict() { [ -z "$bad" ] || { echo "$1:$bad" >&2; exit 1; }; }
'''


class D2ReadsClosed(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(orch, "slice_line", return_value=orch.NO_SLICE))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text", return_value="$ "))
        self.stack.enter_context(patch.object(worker, "auth_ok", return_value=(True, "stub")))
        self.seat = {"name": "atoll", "path": str(self.root), "created": 1, "attached": False,
                     "exited": False, "legacy": False, "resumable": False}
        config.save_session(self.cfg, "atoll", "fable", ["opus"], {"cwd": str(self.root)})

    def listing(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.cmd_why(["atoll"]), 0)
        return out.getvalue()

    def d2(self, listing):
        path = self.root / "listing.txt"
        path.write_text(listing)
        work = self.root / "work"
        (work / "pty").mkdir(parents=True, exist_ok=True)
        return subprocess.run(
            ["bash", "-c", FAKES + D2], capture_output=True, text=True,
            env={"PATH": os.environ["PATH"], "WORK": str(work), "SEATLOGIN": "acme",
                 "LISTING": str(path)})

    def test_a_seat_the_owner_stopped_passes(self):
        # tmux holds no seat (the sandbox's), so only its record lists it
        orch.mark_owner_closed("atoll")
        listing = self.listing()
        done = self.d2(listing)
        self.assertEqual(done.returncode, 0, listing + done.stderr)

    def test_a_seat_stop_left_working_fails(self):
        # Stop marks the seat before its kill, so a kill that failed leaves the mark on a seat
        # still going: here one of its runs is.
        orch.mark_owner_closed("atoll")
        directory = config.RUNS / "20261016-0900-going"
        directory.mkdir(parents=True)
        record.save_state(directory, {"run_id": directory.name, "title": "Going",
                                      "state": "running", "launched_session": "atoll",
                                      "pid": os.getpid(), "started_at": 1, "reported": False})
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))
        listing = self.listing()
        self.assertIn("atoll  working", listing)
        done = self.d2(listing)
        self.assertEqual(done.returncode, 1, listing + done.stderr)
        self.assertIn("atoll does not read closed by the owner", done.stderr)


if __name__ == "__main__":
    unittest.main()
