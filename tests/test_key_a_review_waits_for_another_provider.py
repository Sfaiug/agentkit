"""A task's review that loses its reviewer goes to a model of its writer's lab only while no
other marked reviewer of another lab that has not failed this round can run here with usage
left: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."; 22 Nov: "Own lab reviews when spent".
opus alone builds.  Where astra, on another provider, reviews and its window is spent by its
turn, opus reviews its own work, as it does where the reviewer spent so is fable, on opus's
provider, and where astra's harness is gone from the machine by its turn.  Black-box, staged as
tests/test_key_writer_reviews_only_without_room.py stages it.
"""

import shlex
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import fakeadapter, taskfile
from test_key_writer_reviews_only_without_room import (launched, meter, record, roles, staged,
                                                       until_true)

# how long the window a reviewer's turn is refused on lasts from that turn
SHORTAGE = 20
# a turn of an adapter whose program is gone: the shell's exec found nothing, and nothing streamed
GONE = {"stderr": "codex.sh: 1: exec: codex: not found\n", "exit": 127}


def refused(seconds):
    """A turn its harness refuses, the window spent for `seconds` from the turn."""
    return {"final": f"You have hit your usage limit. Try again at {{in {seconds}}}.", "exit": 1}


def launch(case):
    home = case.home
    case.done = home.ak("run", str(taskfile.write(home, case.rig.path)), "--no-merge",
                        timeout=300)
    case.run_dir = taskfile.only_run(home)
    case.state = record(case.run_dir)


class AnotherProvidersReviewerIsSpent(unittest.TestCase):
    """opus and astra review; astra, picked at launch, is refused at its turn."""

    @classmethod
    def setUpClass(cls):
        week = [meter(10, time.time() + 86400)]
        staged(cls, ["opus", "astra"], ["opus", "astra"], {"claude": week, "codex": week},
               claude=["work", "pass"], codex=refused(SHORTAGE))
        launch(cls)

    def test_with_the_other_labs_reviewer_spent_the_writers_lab_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "astra"))
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual((self.state["reviewer"], self.state["review"]["reviewer"]),
                         ("opus", "opus"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


class OwnProvidersReviewerGivesWayToTheWriter(unittest.TestCase):
    """opus and fable, on opus's provider, review; fable, picked at launch, is refused at its
    turn."""

    @classmethod
    def setUpClass(cls):
        now = time.time()
        # fable's own cap beside the shared week: fable's refusal leaves opus to its meters
        scoped = {**meter(10, now + 86400), "name": "weekly_scoped", "scope": "Fable"}
        staged(cls, ["opus", "fable"], ["opus", "fable"],
               {"claude": [meter(10, now + 86400), scoped]},
               claude=["work", refused(3600), "pass"])
        launch(cls)

    def test_opus_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "fable"))
        self.assertEqual([(run["role"], run["argv"][0]) for run in self.fakes["claude"].runs()],
                         [("executor", "claude-opus-5-5"), ("reviewer", "claude-fable-5-1"),
                          ("reviewer", "claude-opus-5-5")])
        self.assertEqual(self.state["review"]["reviewer"], "opus")
        self.assertEqual(self.state["verdict"], "PASS")


class AnotherProvidersHarnessIsGone(unittest.TestCase):
    """As the first, but codex, astra's harness, is gone from the machine during the build."""

    @classmethod
    def setUpClass(cls):
        week = [meter(10, time.time() + 86400)]
        home = staged(cls, ["opus", "astra"], ["opus", "astra"], {"claude": week, "codex": week},
                      claude="work", codex=GONE)
        # codex's program by its path in the Home, the one this test removes: a codex the
        # machine has on its PATH would stand in for the name
        program = home.bin / "codex"
        manifest, named = cls.fakes["codex"].manifest, 'version = ["codex", "--version"]'
        assert named in manifest.read_text(), "the shipped codex.toml names its program otherwise"
        manifest.write_text(manifest.read_text().replace(
            named, f'version = [{fakeadapter.toml(str(program))}, "--version"]'))
        release = cls.fakes["claude"].dir / "release"
        cls.fakes["claude"].behave(
            {**fakeadapter.WORK,
             "sh": f"until [ -f {shlex.quote(str(release))} ]; do sleep 0.2; done"}, "pass")

        def uninstall():
            until_true(lambda: cls.fakes["claude"].n)      # the build has begun
            program.unlink()
            release.touch()

        threading.Thread(target=uninstall, daemon=True).start()
        launch(cls)

    def test_opus_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "astra"))
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual(self.state["review"]["reviewer"], "opus")
        self.assertEqual(self.state["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
