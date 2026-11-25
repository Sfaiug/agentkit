"""A run draws its executor among the role's marks, and its reviewer too (the owner, 24 Nov 2026:
"exec if multiple, then choose randomly 50/50 no preferance, and reviewer also randomly 50/50 no
preferance, prefering a model from a different company comapred to the exec").

Two executors are marked, opus and then astra, each on a harness and provider of its own.  On
`ak usage --json`'s `pick_order`: one `AK_PICK_DRAW` gives one order however often it is asked,
over a fixed list of draws each comes first at least once, and with it empty they come as
marked.  With `AK_PICK_DRAW` out of the environment, a run launched with `--bg` and one launched
without each record as executor the one `pick_order` names first under `AK_PICK_DRAW` set to
that run's id: the id is the run's draw, in the parent that picks for a `--bg` launch and in the
run.  An id holds the minute it was made, so which executor it draws is left to the fixed draws.
The seam is the launch's alone: a run of a repository whose env file sets it, read by the run
after a `--bg` launch has picked, ends naming that file and line.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
harnesses the fakes of tests/fixtures/fakeadapter.py, on the bare origin of gitrig.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from fixtures.gitrig import Rig
from test_key_writer_reviews_only_without_room import record, staged, until_true

MARKED = ["opus", "astra"]
DRAWS = [f"20261124-09{minute:02d}-acme-parser" for minute in range(12)]


def ended(state):
    return state.get("state") not in (None, "running", "queued", "waiting")


class ARunDrawsItsExecutor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        staged(cls, MARKED, MARKED, {}, workers=MARKED, claude="work", codex="work")
        # a repository of its own, so only its runs read the file that sets the seam
        cls.seamed = Rig(cls.home, "parser")
        cls.env_file = cls.home.write(".agentkit/env/parser.env",
                                      "SMOKE_REGION=north\nAK_PICK_DRAW=20261124-0900\n")

    def pick_order(self, draw):
        done = self.home.ak("usage", "--json", env={"AK_PICK_DRAW": draw})
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)["pick_order"]

    def test_one_draw_gives_one_order_however_often_it_is_asked(self):
        self.assertEqual(len({tuple(self.pick_order(DRAWS[0])) for _ in range(3)}), 1)

    def test_over_the_draws_each_executor_comes_first(self):
        self.assertEqual({self.pick_order(draw)[0] for draw in DRAWS}, set(MARKED))

    def test_with_no_draw_they_come_as_marked(self):
        self.assertEqual(self.pick_order(""), MARKED)

    def launch(self, rig, title, *flags):
        """The record a run of `title` on `rig`, launched with `flags` and no `AK_PICK_DRAW`,
        ends with, and its id."""
        known = set(taskfile.runs(self.home))
        task = taskfile.write(self.home, rig.path, title)
        done = self.home.ak("run", str(task), "--no-merge", *flags, env={"AK_PICK_DRAW": None},
                            timeout=300)
        new = set(taskfile.runs(self.home)) - known
        self.assertEqual(len(new), 1, done.out + done.err)
        run_dir, = new
        until_true(lambda: ended(record(run_dir)), bound=300)
        return done, record(run_dir), run_dir.name

    def assert_draws(self, title, *flags):
        """A run of `title` launched with `flags` records as executor the one its id draws first."""
        done, state, run_id = self.launch(self.rig, title, *flags)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(state["executor"], self.pick_order(run_id)[0])

    def test_a_run_launched_without_bg_records_the_executor_its_id_draws(self):
        self.assert_draws("Add retry file here")

    def test_a_run_launched_with_bg_records_the_executor_its_id_draws(self):
        self.assert_draws("Add retry file apart", "--bg")

    def assert_refused(self, title, *flags):
        """A run of `title` on the repository whose env file sets the seam ends naming its line."""
        done, state, _ = self.launch(self.seamed, title, *flags)
        self.assertEqual(state["state"], "error", done.out + done.err)
        self.assertIn(f"{self.env_file}:2:", state["error"])

    def test_a_run_launched_without_bg_ends_on_an_env_file_setting_the_draw(self):
        self.assert_refused("Add parser file here")

    def test_a_run_launched_with_bg_ends_on_an_env_file_setting_the_draw(self):
        self.assert_refused("Add parser file apart", "--bg")


if __name__ == "__main__":
    unittest.main()
