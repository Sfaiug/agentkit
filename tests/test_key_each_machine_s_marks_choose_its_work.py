"""Machine marks on c decide placement. Black-box: a terminal, fake SSH and boxed containers."""

from pathlib import Path
import sys
import time
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

    def write_config(self, *, turns=True, cloud=None):
        akconfig.write(self.home, ["opus", "astra"],
                       settings={"turns_on_machines": turns, "suite_helper": "acme-linux"},
                       extra="[machines.acme-linux]\n" + ("[google_cloud]\nactive = true\n"
                             f"max_month = 200\n{cloud}\n" if cloud is not None else ""))
        if cloud is not None:
            self.home.write(".agentkit/state/google-cloud-ssh-config",
                            f"Host acme-linux\n  # until {int(time.time()) + 21600}\n")

    def marks(self, *, cloud=False, keys=("Space",)):
        term = Terminal(self.home, "attach", "--overlay", size=(120, 35), env={"NO_COLOR": "1"})
        term.wait("esc leave")
        term.keys("c")
        term.wait("Machines")
        term.keys(*(["Down"] * 7), "Enter")
        term.wait("config · machines")
        term.keys("Down", *(["Down"] if cloud else []), "Enter")
        term.wait("builds and reviews")
        term.keys(*keys)
        term.keys("Escape")
        shown = term.wait(lambda screen: "acme-linux" in screen and "builds and reviews" not in screen)
        term.keys("Escape", "Escape", "Escape")
        self.assertEqual(term.exit_code(), 0)
        return " ".join(shown.split())

    def turns(self, where):
        task = taskfile.write(self.home, self.line.rig.path, done_when=("test -f left.txt",))
        done = self.home.ak("run", str(task), "--no-merge", timeout=300)
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

    def test_a_rental_unmarked_for_tests_still_takes_turns(self):
        self.write_config(cloud="")
        shown = self.marks(cloud=True, keys=("Down", "Space"))
        self.assertIn("never answered · builds, reviews", shown)
        self.assertEqual(akconfig.read(self.home)["google_cloud"]["work"], ["turns"])
        self.turns("docker")
        self.suite(False)
        self.assertFalse((self.home.path / ".agentkit/state/google-cloud-need").exists())

    def test_the_old_switch_reads_as_before_and_c_replaces_it(self):
        self.write_config(turns=False, cloud="")
        self.turns("here")
        self.marks(cloud=True, keys=("Space", "Space"))
        cfg = akconfig.read(self.home)
        self.assertNotIn("turns_on_machines", cfg)
        self.assertEqual(cfg["google_cloud"]["work"], ["tests"])
        self.suite(True)

    def test_cloud_turns_do_not_change_an_owned_helper_s_work(self):
        for turns in (True, False):
            with self.subTest(turns=turns):
                self.write_config(turns=turns, cloud="")
                (self.home.path / ".agentkit/state/google-cloud-ssh-config").unlink()
                shown = self.marks(cloud=True)
                work = (["turns"] if turns else []) + ["tests"]
                self.assertEqual(akconfig.read(self.home)["machines"]["acme-linux"]["work"], work)
                words = "builds, reviews, tests" if turns else "tests"
                self.assertIn(f"acme-linux new · never answered · {words}", shown)

    def test_no_marks_leave_both_kinds_here_without_asking_for_a_rental(self):
        self.write_config(cloud='work = []')
        self.turns("here")
        self.suite(False)
        self.assertFalse((self.home.path / ".agentkit/state/google-cloud-need").exists())

    def test_a_rental_s_row_edits_the_shared_cloud_marks(self):
        self.write_config(cloud="")
        self.marks()
        cfg = akconfig.read(self.home)
        self.assertEqual(cfg["google_cloud"]["work"], ["tests"])
        self.assertNotIn("work", cfg["machines"]["acme-linux"])

    def test_unknown_work_words_are_refused_and_name_the_valid_words(self):
        for table in ("machines.acme-linux", "google_cloud"):
            akconfig.write(self.home, ["opus"], extra=f'[{table}]\nwork = ["builds"]\n')
            done = self.home.ak("models", "--json")
            self.assertEqual(done.code, 2, done.out + done.err)
            self.assertIn(f"[{table}].work", done.err)
            self.assertIn("turns and tests", done.err)


if __name__ == "__main__":
    unittest.main()
