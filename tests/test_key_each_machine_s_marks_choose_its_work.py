"""Machine marks on c decide placement. Black-box: a terminal, fake SSH and boxed containers."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home, REAL_TMUX
from fixtures.akline import Line
from fixtures.akterm import Terminal

WHERE = 'echo "${container:-here}" >"${AK_HAND_IN%/*}/where"'


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EachMachinesMarks(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.line = Line({"t/a.sh": "true\n", "tools/helper/Containerfile": "FROM acme\n"}, home=home)
        fakeadapter.install(home, claude={"sh": WHERE + "; echo left >left.txt", "hand_in": [["done"]]},
                            codex={"sh": WHERE, "hand_in": [["done"]]})
        self.machine = akmachine.install(home)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            place = self.machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        self.write_config()

    def write_config(self, *, turns=True, marks=""):
        akconfig.write(self.home, ["opus", "astra"],
                       settings={"turns_on_machines": turns, "suite_helper": "acme-linux"},
                       extra=f"[machines.acme-linux]\n{marks}")

    def marks(self, *, keys=("Space",)):
        term = Terminal(self.home, "attach", "--overlay", size=(120, 35), env={"NO_COLOR": "1"})
        term.wait("esc leave")
        term.keys("c")
        term.wait("Machines")
        term.keys(*(["Down"] * 6), "Enter")
        term.wait("config · machines")
        term.keys("Down", "Enter")
        term.wait("builds and reviews")
        term.keys(*keys)
        term.keys("Escape")
        shown = term.wait(lambda screen: "acme-linux" in screen and "builds and reviews" not in screen)
        term.keys("Escape", "Escape", "Escape")
        self.assertEqual(term.exit_code(), 0)
        return " ".join(shown.split())

    def turns(self, where):
        task = taskfile.write(self.home, self.line.rig.path, done_when=("test -f left.txt",))
        done = self.home.ak("run", str(task), "--no-merge", timeout=300,
                            env={"AK_HOST_READINGS": akmachine.CROWDED})
        self.assertEqual(done.code, 0, done.out + done.err)
        places = [path.read_text().strip() for path in taskfile.only_run(self.home).rglob("where")]
        self.assertEqual(places, [where, where])

    def suite(self, away):
        self.line.member({"api.txt": "x\n"})
        done = self.line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(bool(self.line.runs()), not away)
        logs = [*self.machine.glob("docker/roots/*/home/ak/work/.git/suite.log")]
        self.assertEqual(bool(logs), away)

    def test_a_helper_unmarked_for_turns_still_takes_a_suite(self):
        self.assertIn("acme-linux new · never answered · tests", self.marks())
        cfg = akconfig.read(self.home)
        self.assertEqual(cfg["machines"]["acme-linux"]["work"], ["tests"])
        self.assertNotIn("turns_on_machines", cfg)
        self.turns("here")
        self.suite(True)

    def test_a_helper_unmarked_for_tests_still_takes_turns(self):
        shown = self.marks(keys=("Down", "Space"))
        self.assertIn("acme-linux new · never answered · builds, reviews", shown)
        self.assertEqual(akconfig.read(self.home)["machines"]["acme-linux"]["work"], ["turns"])
        self.turns("docker")
        self.suite(False)

    def test_the_old_switch_reads_as_before_and_c_replaces_it(self):
        self.write_config(turns=False)
        self.turns("here")
        self.marks(keys=("Space", "Space"))
        cfg = akconfig.read(self.home)
        self.assertNotIn("turns_on_machines", cfg)
        self.assertEqual(cfg["machines"]["acme-linux"]["work"], ["tests"])
        self.suite(True)

    def test_no_marks_leave_both_kinds_here(self):
        self.write_config(marks="work = []\n")
        self.turns("here")
        self.suite(False)

    def test_unknown_work_words_are_refused_and_name_the_valid_words(self):
        akconfig.write(self.home, ["opus"], extra='[machines.acme-linux]\nwork = ["builds"]\n')
        done = self.home.ak("models", "--json")
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertIn("[machines.acme-linux].work", done.err)
        self.assertIn("turns and tests", done.err)

    def test_a_table_left_from_renting_is_not_read(self):
        akconfig.write(self.home, ["opus"], extra='[google_cloud]\nwork = ["builds"]\n')
        done = self.home.ak("models", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)


if __name__ == "__main__":
    unittest.main()
