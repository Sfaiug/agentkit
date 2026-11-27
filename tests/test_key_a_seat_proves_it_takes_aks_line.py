"""One probe proves on a seat that ak's longest line is sent and its turn reads as working.

Runs `tests/probe_seat.py` as a program in an answer-key Home (tests/fixtures/akbin.py) against
fake seats (tests/fixtures/akseat.py):

- a seat that takes the line, reads working and returns to its prompt exits 0, having received
  the full-length line once, whole, with one Enter;
- a seat whose composer never reads as the line typed exits 1 naming step 2, with no Enter
  pressed;
- a seat that takes the line and never reads working exits 1 naming step 3;
- a seat that never reaches its prompt (step 1) or never returns to it (step 4) exits 1 naming
  that step and the last rows of its screen.
"""

from pathlib import Path
import sys
import threading
import time
import tomllib
import unittest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
PROBE = TESTS / "probe_seat.py"

sys.path.insert(0, str(TESTS))
from fixtures.akbin import REAL_TMUX, Home  # noqa: E402
from fixtures.akseat import Seat  # noqa: E402

PROMPT = "claude-prompt-pane.txt"
WORKING = "claude-working-pane.txt"


def longest():
    """The longest line ak types, read directly from adapters/*.toml without importing agentkit."""
    folds = [tomllib.loads(path.read_text(encoding="utf-8")).get("screen", {}).get("folds_over")
             for path in (REPO / "adapters").glob("*.toml")]
    return min([fold for fold in folds if fold] or [8000])


def captures(home):
    """How many capture-pane calls the probe has made in `home` so far."""
    return sum(1 for call in home.calls("tmux") if "capture-pane" in call)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatProvesItTakesAksLine(unittest.TestCase):
    def start_probe(self, home, name, wait):
        """Run probe_seat.py in a background thread so the test can advance the fake seat."""
        box = {}
        thread = threading.Thread(target=lambda: box.setdefault(
            "done", home.run(sys.executable, str(PROBE), name, "--wait", str(wait))))
        thread.start()
        return thread, box

    def wait_captures(self, home, target, thread, bound=30):
        """Wait until the probe has made at least `target` capture-pane calls (or exited)."""
        deadline = time.monotonic() + bound
        while captures(home) < target and thread.is_alive():
            if time.monotonic() > deadline:
                raise AssertionError(f"probe made {captures(home)} captures, wanted {target}")
            time.sleep(0.05)

    def test_seat_takes_line_works_and_returns_to_prompt(self):
        with Home(tmux_log=True) as home:
            seat = Seat(home, "acme", screen=PROMPT)
            thread, box = self.start_probe(home, "acme", wait=30)
            try:
                lines = seat.wait_lines(1)
                seat.show(WORKING)
                # Every capture logged after seat.show finished _settle() reads WORKING. At most
                # one can be type_checked's _wait_sent and the next is step 3; once a third starts,
                # step 3 has already seen WORKING and the probe is polling step 4.
                self.wait_captures(home, captures(home) + 3, thread)
                seat.show(PROMPT)
                thread.join(30)
            finally:
                if thread.is_alive():
                    home.close()
                    thread.join(30)
            self.assertFalse(thread.is_alive(), "probe did not finish")
            done = box["done"]
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(len(lines), 1)
            line = lines[0]
            self.assertEqual(len(line), longest())
            self.assertIn("sleep 20", line)
            self.assertNotIn("\n", line)
            self.assertNotIn("\r", line)
            self.assertEqual(seat.typed(), line + "\r")

    def test_composer_never_reads_as_line_fails_step_2_without_enter(self):
        with Home() as home:
            # A composer mark absent from the screen keeps akpane.py from echoing the draft.
            seat = Seat(home, "acme", screen=PROMPT, composer="never-drawn")
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "1")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("step 2", done.err)
            self.assertIn("bypass permissions", done.err)
            self.assertEqual(seat.lines(), [])
            self.assertNotIn("\r", seat.typed())
            self.assertNotIn("\n", seat.typed())
            self.assertEqual(len(seat.typed()), longest())

    def test_seat_never_reads_working_fails_step_3(self):
        with Home() as home:
            seat = Seat(home, "acme", screen=PROMPT)
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "1")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("step 3", done.err)
            self.assertIn("bypass permissions", done.err)
            self.assertEqual(len(seat.lines()), 1)
            self.assertEqual(len(seat.lines()[0]), longest())

    def test_seat_never_at_prompt_fails_step_1(self):
        with Home() as home:
            seat = Seat(home, "acme", screen=WORKING)
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "0")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("step 1", done.err)
            self.assertIn("Baking…", done.err)
            self.assertEqual(seat.typed(), "")

    def test_seat_never_returns_to_prompt_fails_step_4(self):
        with Home() as home:
            seat = Seat(home, "acme", screen=PROMPT)
            thread, box = self.start_probe(home, "acme", wait=4)
            try:
                seat.wait_lines(1)
                seat.show(WORKING)
                thread.join(30)
            finally:
                if thread.is_alive():
                    home.close()
                    thread.join(30)
            self.assertFalse(thread.is_alive(), "probe did not finish")
            done = box["done"]
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("step 4", done.err)
            self.assertIn("Baking…", done.err)


if __name__ == "__main__":
    unittest.main()
