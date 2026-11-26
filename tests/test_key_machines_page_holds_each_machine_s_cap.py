"""The Machines page on `c` holds each machine's cap on runs at once, the home's among them: Enter
on its row opens its page, whose one row reads and writes the top-level `max_runs` a run is
admitted under, as a listed machine's page holds its own.

Black-box: AK_BIN runs under a terminal in a temporary HOME with an invented machine and no
AK_MAX_RUNS but where a test sets one. `runs at once` reads `no limit` or the cap, and nothing is
written until Enter opens a field where a whole number of 1 or more sets it, 0 or nothing typed
takes the line off and anything else is refused in a sentence. AK_MAX_RUNS overrides the file,
and the row then reads its number and says it sets it.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MachinesPageHoldsEachMachinesCap(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.env.pop("AK_MAX_RUNS")      # the suites' own, over the file under test
        fakeadapter.install(self.home, claude="pass")
        self.config = akconfig.write(self.home, ["fable"], extra="[machines.acme-linux]\n")

    def open_home(self, env=None):
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40),
                             env={"NO_COLOR": "1", **(env or {})})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen
                       and "esc back" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        on_home = self.term.wait(lambda screen: "config · machines" in screen
                                 and "› this one" in screen and "esc back" in screen)
        keys = next(line for line in reversed(on_home.splitlines()) if line.strip())
        self.assertIn("⏎ open", keys)
        self.assertNotIn("␣", keys)
        self.term.keys("Enter")
        return self.term.wait(lambda screen: "config · machines · this one" in screen
                              and "› runs at once" in screen and "esc back" in screen)

    def save(self, typed, shown):
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        if typed:
            self.term.type(typed)
        self.term.keys("Enter")
        self.term.wait(lambda screen: f"runs at once {shown}" in " ".join(screen.split())
                       and "⏎ open" in screen)

    def admitted(self):
        done = self.home.ak("run", "status")
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out.splitlines()[0]

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)

    def test_the_home_s_cap_is_set_read_back_and_taken_off_again(self):
        before = self.config.read_bytes()
        self.assertIn("runs at once no limit", " ".join(self.open_home().split()))
        self.assertEqual(self.config.read_bytes(), before)

        # A whole number of 1 or more is the home's max_runs, and what a run is admitted under.
        self.save("2", "2")
        cfg = akconfig.read(self.home)
        self.assertEqual(cfg["max_runs"], 2)
        self.assertNotIn("max_runs", cfg["machines"]["acme-linux"])
        self.assertIn("at most 2 runs at once", self.admitted())
        self.leave()

        # Reopening reads it back; 0 takes the line off.
        self.assertIn("runs at once 2", " ".join(self.open_home().split()))
        self.save("0", "no limit")
        self.assertNotIn("max_runs", akconfig.read(self.home))
        self.assertNotIn("runs at once", self.admitted())

        # Nothing typed also takes the line off.
        self.save("3", "3")
        self.assertEqual(akconfig.read(self.home)["max_runs"], 3)
        self.save("", "no limit")
        self.assertNotIn("max_runs", akconfig.read(self.home))
        self.leave()

    def test_a_word_is_refused_and_changes_nothing(self):
        before = self.config.read_bytes()
        self.open_home()
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        self.term.type("two")
        self.term.keys("Enter")
        screen = self.term.wait(lambda s: "whole number" in " ".join(s.split()) and "⏎ open" in s)
        self.assertIn("runs at once no limit", " ".join(screen.split()))
        self.assertEqual(self.config.read_bytes(), before)
        self.leave()

    def test_a_line_of_0_is_taken_off(self):
        for typed in ("", "0"):
            with self.subTest(typed=typed):
                akconfig.write(self.home, ["fable"], settings={"max_runs": 0})
                self.open_home()
                self.save(typed, "no limit")
                self.assertNotIn("max_runs", akconfig.read(self.home))
                self.leave()

    def test_a_file_changed_under_the_field_is_kept(self):
        akconfig.write(self.home, ["fable"], settings={"max_runs": 2})
        self.open_home()
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        edited = self.config.with_suffix(".edited")     # a hand edit while the field is open
        edited.write_text(self.config.read_text().replace("max_runs = 2\n", ""))
        edited.replace(self.config)
        before = self.config.read_bytes()
        self.term.keys("Enter")
        self.term.wait("that key was not taken")
        self.assertEqual(self.config.read_bytes(), before)
        self.leave()

    def test_no_cap_to_take_off_writes_nothing(self):
        # a home file with no models, which config.load fills from the shipped file
        before = self.home.write(".agentkit/config.toml", "# acme\nmax_load = 0\n").read_bytes()
        self.term = Terminal(self.home, page="config_machines", size=(120, 40),
                             env={"NO_COLOR": "1"})
        self.term.wait(lambda screen: "config · machines" in screen and "› this one" in screen
                       and "esc back" in screen)
        self.term.keys("Enter")
        self.term.wait("› runs at once")
        for typed in ("", "0"):
            with self.subTest(typed=typed):
                self.save(typed, "no limit")
                self.assertEqual(self.config.read_bytes(), before)
        self.term.keys("Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)

    def test_a_cap_past_the_digits_python_writes_is_kept_and_said(self):
        self.home.env["PYTHONINTMAXSTRDIGITS"] = "640"     # ak's limit, not the test's
        long = "1" * 641
        self.assertIn("set by AK_MAX_RUNS", " ".join(self.open_home({"AK_MAX_RUNS": long}).split()))
        self.save(long, "")
        self.assertEqual(akconfig.read(self.home)["max_runs"], int(long))
        self.assertIn(f"at most {hex(int(long))} runs at once", self.admitted())
        self.leave()

    def test_ak_max_runs_is_the_number_in_force_and_says_so(self):
        akconfig.write(self.home, ["fable"], settings={"max_runs": 2})
        shown = " ".join(self.open_home({"AK_MAX_RUNS": "4"}).split())
        self.assertIn("runs at once 4 set by AK_MAX_RUNS", shown)
        # the file's line is still the one a number typed writes
        self.save("3", "4 set by AK_MAX_RUNS")
        self.assertEqual(akconfig.read(self.home)["max_runs"], 3)
        self.leave()


if __name__ == "__main__":
    unittest.main()
