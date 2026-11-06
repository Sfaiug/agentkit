"""A first build's `ak hand-in done` counts the workspace's added lines as the size gate does.

Black-box through AK_BIN and fakeadapter, `executor_lines = 40`: an uncommitted 60-line change is
refused with both ways on, fewer lines never meaning denser ones, the same change in 30 lines is
taken and reaches review; lines under a path the base's `.gitattributes` marks generated never
count, and `no limit` counts nothing.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, Home
from fixtures.gitrig import Rig

TABLE = "table.txt"


class DoneCountsTheLines(unittest.TestCase):
    def build(self, step, limit=40, files=None):
        """The executor's turn, once a run whose executor does `step` and hands in done has
        reached review and passed it."""
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"], settings={"executor_lines": limit})
        rig = Rig(home, "widgets", files=files)
        fakes = fakeadapter.install(home, claude={**step, "final": "## Summary\nwrote it",
                                                  "hand_in": [["done"]]}, codex="pass")
        task = taskfile.write(home, rig.path, "Rewrite the table", done_when=(f"test -f {TABLE}",))
        done = home.ak("run", str(task), "--no-merge", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual([run["role"] for run in fakes["codex"].runs()], ["reviewer"])
        self.assertEqual(state["verdict"], "PASS")
        return fakes["claude"].runs()[0]

    def test_sixty_lines_are_refused_and_the_same_change_in_thirty_is_taken(self):
        out = '"$(dirname "$AK_HAND_IN")"'
        turn = self.build({"sh": f"seq 60 > {TABLE}; {shlex.quote(AK)} hand-in done > {out}/said 2>&1; "
                                f"echo $? > {out}/code; seq 30 > {TABLE}"})
        said = Path(turn["argv"][4], "said").read_text()
        self.assertNotEqual(Path(turn["argv"][4], "code").read_text().strip(), "0", said)
        for text in ("adds 60 lines", "at most 40", "same change in fewer lines",
                     "every asked-for behaviour kept", "formatted as the project formats code",
                     "a denser line is no smaller a change", "ak hand-in blocked", "the pieces it splits into"):
            self.assertIn(text, said)
        for word in ("cut", "drop", "scope"):
            self.assertNotIn(word, said.lower())
        self.assertEqual(turn["hand_ins"][0]["code"], 0, turn["hand_ins"])

    def test_lines_under_a_path_the_base_marks_generated_never_count(self):
        go = "".join(f"line {n}\n" for n in range(400))
        turn = self.build({"write": {"go/table.go": go, TABLE: "row\n" * 30}},
                          files={".gitattributes": "go/** linguist-generated\n"})
        self.assertEqual(turn["hand_ins"][0]["code"], 0, turn["hand_ins"])

    def test_no_limit_counts_nothing(self):
        turn = self.build({"write": {TABLE: "row\n" * 60}}, limit="no limit")
        self.assertEqual(turn["hand_ins"][0]["code"], 0, turn["hand_ins"])


if __name__ == "__main__":
    unittest.main()
