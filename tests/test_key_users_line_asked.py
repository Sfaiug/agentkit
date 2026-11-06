"""A seat's task into a project whose AGENTS.md has no `users:` line waits for the owner's answer.

The answer decides whether a reviewer holds a new feature to the project's switch, and only the
owner can give it: so a seat's launch is refused before any run exists, with the question and
both answers, until the task carries the chosen line.  It is read on the default branch, which a
clone with no `origin/HEAD` still finds.  Outside a seat nothing waits.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, with a seat of
tests/fixtures/akseat.py, on projects from gitrig.py with scripted harnesses from fakeadapter.py.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

UNANSWERED = "---\ntests: true\nhealth: none\n---\n"


class UsersLineAsked(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus", "astra"])
        self.fakes = fakeadapter.install(self.home, claude="work", codex="pass")
        Seat(self.home, "acme", alive=False, planned=True)

    def launch(self, rig, *, seat=True, constraints=()):
        task = taskfile.write(self.home, rig.path, "Fix api", constraints=constraints)
        return self.home.ak("run", str(task), "--no-merge", timeout=300,
                            env={"AGENTKIT_SESSION": "acme"} if seat else None)

    def assertLaunched(self, done):
        self.assertEqual(done.code, 0, done.out + done.err)
        taskfile.only_run(self.home)

    def test_a_seat_s_task_is_refused_with_the_question_and_both_lines(self):
        rig = Rig(self.home, "widgets", files={"AGENTS.md": UNANSWERED})
        done = self.launch(rig)
        self.assertEqual((done.code, done.out), (2, ""))
        self.assertEqual(done.err, (
            f"ak run: {rig.path}/AGENTS.md has no users: line. Ask the owner \"Does widgets have "
            "real users?\": \"No, straight to live\" is users: none; \"Yes, new features stay "
            "hidden until I switch them on\" is users: real. Put the chosen line in the task, "
            "which adds it to AGENTS.md.\n"))
        self.assertEqual(taskfile.runs(self.home), [])
        self.assertEqual([fake.n for fake in self.fakes.values()], [0, 0])

    def test_the_same_task_naming_users_real_launches(self):
        rig = Rig(self.home, "widgets", files={"AGENTS.md": UNANSWERED})
        self.assertLaunched(self.launch(rig, constraints=("Add `users: real` to AGENTS.md.",)))

    def test_users_none_is_read_on_a_clone_with_no_origin_head(self):
        rig = Rig(self.home, "widgets",
                  files={"AGENTS.md": "---\ntests: true\nhealth: none\nusers: none\n---\n"})
        rig.git("symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        self.assertLaunched(self.launch(rig))

    def test_outside_a_seat_nothing_waits(self):
        rig = Rig(self.home, "widgets", files={"AGENTS.md": UNANSWERED})
        self.assertLaunched(self.launch(rig, seat=False))


if __name__ == "__main__":
    unittest.main()
