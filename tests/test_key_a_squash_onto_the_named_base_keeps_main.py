"""A worker that squashes its work onto the base its prompt names leaves main's later changes in.

Every run's checkout shares one clone's `origin/main`, and any fetch moves it.  A worker that
squashed onto that name made a commit holding main as the run started plus its work, whose
landing took out of main whatever main merged meanwhile.  Its prompt names, at each turn, the
commit its branch starts from, which ak's own rebase onto the target moves; a checkout behind
origin's tip, such as an older local branch run with --no-worktree, starts from the one commit
where it forks from its base and its target, or failing one from its target alone, and one whose
clone shows no such commit for certain starts no run.

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

    def run_in_the_clone(self, stand, **front):
        """Run the task, with `front` in its front matter, with --no-worktree where `stand` leaves
        the rig's clone, main one change past the commit `topic` forks from, with a worker that
        squashes onto the base its prompt names.  Sets the rig, that fork, the run's exit and
        record, and the base each writing turn's `Branch:` line named."""
        home = Home()
        self.addCleanup(home.close)
        self.rig = Rig(home, "widgets")
        self.fork = self.rig.head()
        self.rig.branch("topic", {"topic.txt": "topic\n"})
        self.rig.commit({"other.txt": "landed on main\n"}, "another change")
        stand()
        GitHub(home).grant(self.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        # main moves before the run, not during it: the turn's own `started` is its `go`
        go = shlex.quote(str(home.root / "adapters" / "go"))
        fakes = fakeadapter.install(home, codex="pass", claude={
            "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]],
            "sh": SQUASH.format(started=go, go=go)})
        self.done = home.ak("run", str(taskfile.write(home, self.rig.path, front=front)),
                            "--no-worktree", timeout=600)
        self.said = self.done.out + self.done.err
        self.state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.told = [BASE.search(Path(call["argv"][3]).read_text())[1] for call in fakes["claude"].runs()]

    def shallow(self, branch, depth):
        """Move the rig into a clone of its origin `depth` commits deep, with `branch` out."""
        clone = self.rig.path.with_name("shallow")
        # git cuts a clone short only of a URL; ak reads the project off the origin's path
        self.rig.git("clone", "-q", f"--depth={depth}", "--no-single-branch", "-b", branch,
                     self.rig.bare.as_uri(), str(clone))
        self.rig.path = clone
        self.rig.git("remote", "set-url", "origin", str(self.rig.bare))

    def test_an_older_local_branch_names_where_it_forks(self):
        def older():
            self.rig.git("checkout", "-q", "-b", "local", "topic")

        def cut_behind():
            # two commits deep the clone still shows where `late` forks, main's commit before last
            self.fork = self.rig.head()
            self.rig.branch("late", {"topic.txt": "topic\n"})
            self.rig.commit({"more.txt": "more\n"}, "one more change")
            self.shallow("late", 2)
            self.rig.git("checkout", "-q", "-b", "local")

        for stand in (older, cut_behind):
            with self.subTest(stand.__name__):
                self.run_in_the_clone(stand)
                self.assertEqual(self.done.code, 0, self.said)
                self.assertTrue(self.state["merged"], self.said)
                self.assertLessEqual({"topic.txt", "retry.txt", "other.txt"}, set(self.rig.files()))
                self.assertEqual(self.told, [self.fork])

    def test_a_branch_cut_from_its_target_names_where_it_forks_from_that(self):
        def cut_from_release():
            self.rig.git("checkout", "-q", "-b", "release")
            self.fork = self.rig.commit({"retired.txt": "in use\n"})
            self.rig.git("branch", "local")
            self.rig.commit({"retired.txt": None}, "retire it")
            self.rig.git("checkout", "-q", "local")

        def holding_more_of_main():
            # main's next commit is none of release's: local, taking it in, holds a commit of
            # each that the other lacks, and still forks from release where it did
            cut_from_release()
            self.rig.git("checkout", "-q", "main")
            self.rig.commit({"more.txt": "more\n"}, "one more change")
            self.rig.git("checkout", "-q", "local")
            self.rig.git("merge", "-q", "--no-edit", "main")

        for stand in (cut_from_release, holding_more_of_main):
            with self.subTest(stand.__name__):
                self.run_in_the_clone(stand, target="release")
                self.assertEqual((self.done.code, self.told), (0, [self.fork]), self.said)
                # squashed onto a commit of main's, its commit would put retired.txt back
                self.assertEqual({"retry.txt", "retired.txt"} & set(self.rig.files("release")),
                                 {"retry.txt"})

    def test_a_branch_with_no_one_certain_fork_starts_no_worker(self):
        def unrelated():
            self.rig.git("checkout", "-q", "--orphan", "local", "topic")
            self.rig.commit({}, "topic's files with no history", push=False)

        def crossed():
            # main took topic in as local, cut from topic, took in main's commit before that
            before = self.rig.head()
            self.rig.git("merge", "-q", "--no-edit", "topic")
            self.rig.git("push", "-q", "origin", "main")
            self.rig.git("checkout", "-q", "-b", "local", "topic")
            self.rig.git("merge", "-q", "--no-edit", before)

        def shallow():
            self.shallow("topic", 1)

        def cut():
            # three commits deep the clone shows `deep` down to where topic forks, the first
            # commit, and not to where it forks itself, main's tip
            self.rig.git("checkout", "-q", "-b", "deep")
            self.rig.commit({"deep.txt": "one\n"}, push=False)
            self.rig.commit({"deep.txt": "two\n"}, push=False)
            self.rig.git("merge", "-q", "--no-edit", "topic")
            self.rig.git("push", "-q", "origin", "deep")
            self.shallow("deep", 3)

        # ak has no base to name such a branch: squashed onto a commit that is not where it
        # forks, its commit would take changes of main's back out
        for stand in (unrelated, crossed, shallow, cut):
            with self.subTest(stand.__name__):
                self.run_in_the_clone(stand)
                self.assertEqual((self.done.code, self.told), (2, []), self.said)
                self.assertIn("cannot tell where HEAD forks from main", self.state["error"])
                self.assertIn("other.txt", self.rig.files())


if __name__ == "__main__":
    unittest.main()
