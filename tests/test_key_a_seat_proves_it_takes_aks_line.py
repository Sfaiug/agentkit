"""One probe proves on a seat that ak's longest line is sent and its turn reads as working.

Runs `tests/probe_seat.py` in an answer-key Home against fake seats, covering the happy path,
broken composer (step 2, no Enter), never working (step 3), step 1/4 timeouts, setup/adapter/send
errors, and shorter adapter cutoffs.
"""

from pathlib import Path
import sys
import threading
import time
import tomllib
import unittest

TESTS = Path(__file__).resolve().parent
REPO, PROBE = TESTS.parent, TESTS / "probe_seat.py"
PROMPT, WORKING = "claude-prompt-pane.txt", "claude-working-pane.txt"

sys.path.insert(0, str(TESTS))
from fixtures.akbin import REAL_TMUX, Home  # noqa: E402
from fixtures.akseat import Seat  # noqa: E402


def longest():
    """The longest line ak types, read from adapters/*.toml without importing agentkit."""
    folds = [tomllib.loads(path.read_text(encoding="utf-8")).get("screen", {}).get("folds_over")
             for path in (REPO / "adapters").glob("*.toml")]
    return min([fold for fold in folds if fold] or [8000])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatProvesItTakesAksLine(unittest.TestCase):
    def drive_probe(self, home, name, wait, drive):
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

    def assertProbeLine(self, line, length):
        self.assertEqual(len(line), length)
        for token in ("sleep 20", "foreground", "OK"):
            self.assertIn(token, line)
        self.assertFalse("\n" in line or "\r" in line, repr(line))

    def test_seat_takes_line_works_and_returns_to_prompt(self):
        with Home(tmux_log=True) as home:
            seat = Seat(home, "acme", screen=PROMPT)
            captures = lambda: sum("capture-pane" in call for call in home.calls("tmux"))

            def drive(thread):
                lines = seat.wait_lines(1)
                seat.show(WORKING)
                # Captures logged after _settle() read WORKING; at most one is _wait_sent and
                # the next is step 3, so a third means step 3 passed and step 4 is polling.
                target, deadline = captures() + 3, time.monotonic() + 30
                while captures() < target and thread.is_alive():
                    self.assertLess(time.monotonic(), deadline, "probe stopped capturing")
                    time.sleep(0.05)
                seat.show(PROMPT)
                return lines

            done, lines = self.drive_probe(home, "acme", 30, drive)
            self.assertEqual((done.code, len(lines)), (0, 1), done.out + done.err)
            self.assertProbeLine(lines[0], longest())
            self.assertEqual(seat.typed(), lines[0] + "\r")

    def test_composer_never_reads_as_line_fails_step_2_without_enter(self):
        with Home() as home:
            # A composer mark absent from the screen keeps akpane.py from echoing the draft.
            seat = Seat(home, "acme", screen=PROMPT, composer="never-drawn")
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "1")
            self.assertEqual((done.code, seat.lines()), (1, []), done.out + done.err)
            self.assertIn("step 2:", done.err)
            self.assertIn("bypass permissions", done.err)
            self.assertProbeLine(seat.typed(), longest())

    def test_seat_never_reads_working_fails_step_3_even_with_zero_wait(self):
        with Home() as home:
            seat = Seat(home, "acme", screen=PROMPT)
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "0")
            self.assertEqual((done.code, len(seat.lines())), (1, 1), done.out + done.err)
            self.assertIn("step 3:", done.err)
            self.assertIn("bypass permissions", done.err)
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
            done, _ = self.drive_probe(home, "acme", 4, lambda _t: (seat.wait_lines(1), seat.show(WORKING)))
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn("step 4:", done.err)
            self.assertIn("Baking…", done.err)

    def test_setup_adapter_and_send_errors_report_step_and_screen_rows(self):
        cases = ((1, "config"), (2, "receipt"), (1, "claude.toml"), (2, "acme.toml"), (2, "short"))
        for step, kind in cases:
            with self.subTest(step=step, kind=kind), Home() as home:
                seat, env = Seat(home, "acme", screen=PROMPT), None
                if kind == "config":
                    home.write(".agentkit/config.toml", "[providers.\n")
                elif kind == "receipt":
                    (home.path / ".agentkit/state/input-acme.jsonl").mkdir()
                else:
                    adapters = home.root / "adapters"
                    adapters.mkdir()
                    body = ("[screen]\nfolds_over = 8\n" if kind == "short"
                            else '[[rule]]\nstate = "at_prompt"\nlines = "six"\n')
                    (adapters / ("acme.toml" if kind == "short" else kind)).write_text(body)
                    env = {"AGENTKIT_ADAPTER_DIR": str(adapters)}
                done = home.run(sys.executable, str(PROBE), "acme", "--wait", "1", env=env)
                self.assertEqual((done.code, seat.typed()), (1, ""), done.out + done.err)
                self.assertIn(f"step {step}:", done.err)
                self.assertIn("bypass permissions", done.err)

    def test_short_adapter_cutoff_keeps_both_instructions(self):
        with Home() as home:
            adapters = home.root / "adapters"
            adapters.mkdir()
            (adapters / "acme.toml").write_text("[screen]\nfolds_over = 40\n")
            seat = Seat(home, "acme", screen=PROMPT)
            done = home.run(sys.executable, str(PROBE), "acme", "--wait", "0",
                            env={"AGENTKIT_ADAPTER_DIR": str(adapters)})
            self.assertEqual((done.code, len(seat.lines())), (1, 1), done.out + done.err)
            self.assertIn("step 3:", done.err)
            self.assertProbeLine(seat.lines()[0], 40)


if __name__ == "__main__":
    unittest.main()
