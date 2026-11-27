"""One probe proves on a seat that ak's longest line is sent and its turn reads as working.

Runs `tests/probe_seat.py` as a program in an answer-key Home (tests/fixtures/akbin.py) against
fake seats (tests/fixtures/akseat.py), proving the happy path, broken composer (step 2, no Enter),
never working (step 3), step 1/4 timeouts, setup/send errors, and shorter adapter cutoffs.
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
    """The longest line ak types, read from adapters/*.toml without importing agentkit."""
    folds = [tomllib.loads(path.read_text(encoding="utf-8")).get("screen", {}).get("folds_over")
             for path in (REPO / "adapters").glob("*.toml")]
    return min([fold for fold in folds if fold] or [8000])


def captures(home):
    return sum(1 for call in home.calls("tmux") if "capture-pane" in call)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatProvesItTakesAksLine(unittest.TestCase):
    def drive_probe(self, home, name, wait, drive):
        """Run probe_seat.py on a background thread while `drive(thread)` advances the fake seat."""
        box = {}
        thread = threading.Thread(target=lambda: box.setdefault(
            "done", home.run(sys.executable, str(PROBE), name, "--wait", str(wait))))
        thread.start()
        try:
            extra = drive(thread)
            thread.join(30)
        finally:
            if thread.is_alive():
                home.close()
                thread.join(30)
        self.assertFalse(thread.is_alive(), "probe did not finish")
        return box["done"], extra

    def wait_captures(self, home, target, thread, bound=30):
        deadline = time.monotonic() + bound
        while captures(home) < target and thread.is_alive():
            if time.monotonic() > deadline:
                raise AssertionError(f"probe made {captures(home)} captures, wanted {target}")
            time.sleep(0.05)

    def assertProbeLine(self, line, length):
        self.assertEqual(len(line), length)
        for token in ("sleep 20", "foreground", "OK"):
            self.assertIn(token, line)
        self.assertFalse("\n" in line or "\r" in line, repr(line))

    def test_seat_takes_line_works_and_returns_to_prompt(self):
        with Home(tmux_log=True) as home:
            seat = Seat(home, "acme", screen=PROMPT)

            def drive(thread):
                lines = seat.wait_lines(1)
                seat.show(WORKING)
                # Every capture logged after seat.show finished _settle() reads WORKING. At most
                # one is type_checked's _wait_sent and the next is step 3; once a third starts,
                # step 3 has already seen WORKING and the probe is polling step 4.
                self.wait_captures(home, captures(home) + 3, thread)
                seat.show(PROMPT)
                return lines

            done, lines = self.drive_probe(home, "acme", 30, drive)
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(len(lines), 1)
            self.assertProbeLine(lines[0], longest())
            self.assertEqual(seat.typed(), lines[0] + "\r")

    def test_composer_never_reads_as_line_fails_step_2_without_enter(self):
        with Home() as home:
            # A composer mark absent from the screen keeps akpane.py from echoing the draft.
            seat = Seat(home, "acme", screen=PROMPT, composer="never-drawn")
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "1")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("step 2:", done.err)
            self.assertIn("bypass permissions", done.err)
            self.assertEqual(seat.lines(), [])
            self.assertProbeLine(seat.typed(), longest())

    def test_seat_never_reads_working_fails_step_3(self):
        with Home() as home:
            seat = Seat(home, "acme", screen=PROMPT)
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "1")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("step 3:", done.err)
            self.assertIn("bypass permissions", done.err)
            self.assertEqual(len(seat.lines()), 1)
            self.assertProbeLine(seat.lines()[0], longest())

    def test_seat_never_at_prompt_fails_step_1_and_never_returning_fails_step_4(self):
        with Home() as home:
            seat = Seat(home, "acme", screen=WORKING)
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "0")
            self.assertEqual((done.code, seat.typed()), (1, ""), done.out + done.err)
            self.assertIn("step 1:", done.err)
            self.assertIn("Baking…", done.err)
        with Home() as home:
            seat = Seat(home, "acme", screen=PROMPT)
            done, _ = self.drive_probe(
                home, "acme", 4, lambda _t: (seat.wait_lines(1), seat.show(WORKING)))
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("step 4:", done.err)
            self.assertIn("Baking…", done.err)

    def test_setup_and_send_errors_report_step_and_screen_rows(self):
        for step in (1, 2):
            with self.subTest(step=step), Home() as home:
                seat = Seat(home, "acme", screen=PROMPT)
                if step == 1:
                    home.write(".agentkit/config.toml", "[providers.\n")
                else:
                    (home.path / ".agentkit/state/input-acme.jsonl").mkdir()
                done = home.run(sys.executable, str(PROBE), "acme", "--wait", "1")
                self.assertEqual((done.code, seat.typed()), (1, ""), done.out + done.err)
                self.assertIn(f"step {step}:", done.err)
                self.assertIn("bypass permissions", done.err)

    def test_short_adapter_cutoff_keeps_both_instructions(self):
        with Home() as home:
            adapters = home.root / "adapters"
            adapters.mkdir()
            (adapters / "claude.toml").write_text(
                (REPO / "adapters/claude.toml").read_text(encoding="utf-8").replace(
                    "folds_over = 800", "folds_over = 72"), encoding="utf-8")
            seat = Seat(home, "acme", screen=PROMPT)
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "1",
                            env={"AGENTKIT_ADAPTER_DIR": str(adapters)})
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("step 3:", done.err)
            self.assertEqual(len(seat.lines()), 1)
            self.assertProbeLine(seat.lines()[0], 72)


if __name__ == "__main__":
    unittest.main()
