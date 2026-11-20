"""A worker that squashes its work onto the base its prompt names leaves main's later changes in.

Every run's checkout shares one clone's `origin/main`, and any fetch moves it.  A worker that
squashed onto that name made a commit holding main as the run started plus its work, whose
landing took out of main whatever main merged meanwhile.  Its prompt names, at each turn, the
commit its branch starts from, which ak's own rebase onto the target moves.

Black-box: the program `AK_BIN` names runs a task in the foreground through
tests/fixtures/akbin.py, against gitrig.py's origin, fakegh.py's GitHub and fakeadapter.py's
harnesses.  The executor commits its work and waits while the test merges a change into main and
fetches it, then squashes onto the base its prompt's `Branch:` line names.
"""

from pathlib import Path
import json
import re
import shlex
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

BASE = re.compile(r"^Branch: \S+ \(based on ([^,)]*)", re.MULTILINE)
SQUASH = """\
printf 'hello\\n' >retry.txt && git add -A && git commit -qm 'add retry.txt'
touch {started}; while [ ! -e {go} ]; do sleep 0.1; done
base=$(sed -n 's/^Branch: [^ ]* (based on \\([^,)]*\\).*/\\1/p' "$1")
git reset -q --soft "$base" && git commit -qm 'add retry.txt'
"""
NOTES = "".join(f"line {n}\n" for n in range(1, 8))


class ASquashOntoTheNamedBaseKeepsMain(unittest.TestCase):
    def run_while_main_moves(self, moved, *, files=None, edits=None, fixes=(), reviews=("pass",)):
        """Run the task while main takes in `moved` before the executor squashes.  Sets the rig,
        main's commit at launch and after the move, the run's exit and record, and by harness the
        base each turn's `Branch:` line names: claude's turns write, codex's review."""
        home = Home()
        self.addCleanup(home.close)
        self.rig = Rig(home, "widgets", files=files)
        GitHub(home).grant(self.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        directory = home.root / "adapters"
        started, go = directory / "started", directory / "go"
        squash = {"write": edits or {}, "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]],
                  "sh": SQUASH.format(started=shlex.quote(str(started)), go=shlex.quote(str(go)))}
        fakes = fakeadapter.install(home, claude=[squash, *fixes], codex=list(reviews))
        task = taskfile.write(home, self.rig.path)
        self.launched, ended = self.rig.head(), []
        terminal = threading.Thread(target=lambda: ended.append(home.ak("run", str(task), timeout=600)))
        terminal.start()
        while not started.exists() and terminal.is_alive():
            time.sleep(0.1)
        self.tip = self.rig.commit(moved, "another change")
        self.rig.git("fetch", "-q", "origin")
        go.touch()
        terminal.join()
        (self.done,) = ended
        self.said = self.done.out + self.done.err
        self.state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.bases = {harness: [BASE.search(Path(call["argv"][3]).read_text())[1]
                                for call in fake.runs()] for harness, fake in fakes.items()}

    def test_the_run_merges_and_main_keeps_both_changes(self):
        self.run_while_main_moves({"other.txt": "landed meanwhile\n"})
        self.assertTrue(self.state.get("merged"), self.said)
        self.assertEqual(self.done.code, 0, self.said)
        self.assertLessEqual({"retry.txt", "other.txt"}, set(self.rig.files()))

    def test_after_ak_rebased_the_next_turn_names_the_new_base(self):
        # main's change shares a file with the branch's, so ak rebases before the first review,
        # which finds what the fix answers: every turn after it starts from main's new commit
        finding = {"final": "Found one.", "hand_in": [
            ["finding", "retry.txt:1", "says hello alone", "the fixture says so", "--run",
             "! grep -qx hello retry.txt"], ["done"]]}
        fix = {"write": {"retry.txt": "hello again\n"}, "commit": "fix retry.txt",
               "final": "## Summary\nfixed retry.txt", "hand_in": [["done"]]}
        self.run_while_main_moves({"notes.txt": NOTES.replace("line 7", "line seven")},
                                  files={"notes.txt": NOTES}, fixes=[fix], reviews=[finding, "pass"],
                                  edits={"notes.txt": NOTES.replace("line 1", "line one")})
        self.assertEqual(self.done.code, 0, self.said)
        self.assertEqual(self.bases, {"claude": [self.launched, self.tip],
                                      "codex": [self.tip, self.tip]}, self.said)


if __name__ == "__main__":
    unittest.main()
