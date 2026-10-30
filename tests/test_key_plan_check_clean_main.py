"""A plan line's check runs on a clean checkout of origin's default branch, never the seat's own.

`ak plan add` refuses a check that already passes there, and `ak plan` ticks a line once its
check passes there: what the seat's checkout holds (uncommitted files, its branch, a main it has
not pulled) never makes a check pass or fail, so a tick means the work landed.  The check sees
the project's env file `~/.agentkit/env/<checkout name>.env`, as a run's checks do, and none of
ak's or git's own variables, which would point it at the seat or another repository.  Nothing of
the checkout it ran in is left.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, a seat's record from akseat.py filed under a project of gitrig.py.
"""

import re
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

LINE = re.compile(r"- \[(?P<mark>[ x])\] (?P<what>.+?) · check: `(?P<check>[^`]+)` · "
                  r"(?P<project>.+?) · written \d{4}-\d\d-\d\d \d\d:\d\d on (?P<base>[0-9a-f]{12})"
                  r"(?: · done (?P<done>.+))?")
PASSES = ("ak plan: this check already passes on {}'s default branch, so it proves nothing; "
          "write one that fails until the work is done\n")


class PlanHome(unittest.TestCase):
    """A Home with seats filed under their own projects; each test's seat and project are its
    own, so nothing one writes is there for another."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    @classmethod
    def project(cls, seat, name):
        """A project of that name, with the seat filed under it."""
        rig = Rig(cls.home, name)
        Seat(cls.home, seat, cwd=rig.path, record={"repo": str(rig.path)}, alive=False)
        return rig

    def ak(self, rig, seat, *args, env=None):
        """Run `ak` in the seat's checkout as the seat, and see that no checkout of the
        default branch outlives it."""
        done = self.home.ak(*args, env={"AGENTKIT_SESSION": seat, **(env or {})}, cwd=rig.path)
        wt = self.home.path / ".agentkit" / "wt"
        self.assertEqual(sorted(wt.glob("plan-*")) if wt.is_dir() else [], [])
        self.assertEqual(rig.git("worktree", "list", "--porcelain").count("worktree "), 1)
        return done

    def plan(self, seat):
        path = self.home.path / ".agentkit" / "state" / f"plan-{seat}.md"
        return path.read_text().splitlines() if path.is_file() else []

    def add(self, rig, seat, what, check, env=None):
        """The line `ak plan add` printed and wrote, its check having failed."""
        done = self.ak(rig, seat, "plan", "add", what, "--check", check, env=env)
        self.assertEqual(done.code, 0, done.err)
        line = done.out.strip()
        self.assertTrue(LINE.fullmatch(line), line)
        self.assertIn(f" check: `{check}` ", line)
        self.assertEqual(self.plan(seat)[-1], line)
        return line

    def refused(self, rig, seat, what, check, env=None):
        """`ak plan add` refused the check as passing already, and wrote nothing."""
        before = self.plan(seat)
        done = self.ak(rig, seat, "plan", "add", what, "--check", check, env=env)
        self.assertEqual((done.code, done.out, done.err), (2, "", PASSES.format(rig.name)))
        self.assertEqual(self.plan(seat), before)


class AVerificationsChecksShareATree(PlanHome):
    def test_each_finds_the_last_ones_mess_gone_and_the_rest_not_written_again(self):
        rig = self.project("fix-api", "acme")
        rig.commit({".gitignore": "ignored\n", "a": "a\n", "b": "b\n", "check.sh": """
{ git status --porcelain --ignored; cat a; stat -c %y b; } > "$1"
echo x > a; echo x > new; echo x > ignored
exit 1
"""}, "the project")
        checks = [self.home.root / f"seen-{index}" for index in range(3)]
        for seen in checks:
            self.add(rig, "fix-api", seen.name, f"bash check.sh {seen}")
        self.assertEqual(self.ak(rig, "fix-api", "plan").code, 0)
        first, second, third = (seen.read_text().splitlines() for seen in checks)
        self.assertEqual((first[:-1], second, third), (["a"], first, first))

    def test_what_status_cannot_see_is_gone_too(self):
        rig = self.project("fix-ui", "beta")
        rig.commit({"a": "a\n", "d/b": "b\n", "check.sh": """
{ cat a; git status --porcelain --ignored; git ls-files -v; git log -1 --format=%s; git reflog --format=%s
  stat -c '%a %n' . a d d/b; ls -A .. sub "$(git rev-parse --git-dir)"; } > "$1"
eval "$2"
exit 1
"""}, "the project", push=False)
        rig.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(rig.bare), "sub")
        rig.git("config", "-f", ".gitmodules", "submodule.sub.ignore", "untracked")
        rig.commit({}, "with a submodule")
        messes = ("git update-index --skip-worktree a; echo x > a",
                  "git update-index --assume-unchanged a; echo x > a",
                  "chmod 555 d",
                  "chmod 444 d/b",
                  "chmod 555 .",
                  "git -c protocol.file.allow=always submodule update --init -q; echo x > sub/new",
                  "echo x > ../beside",
                  'echo x > "$(git rev-parse --git-dir)/left"',
                  "git checkout -q --detach HEAD~1",
                  "git -c user.name=a -c user.email=a@b.c commit -q --allow-empty -m moved",
                  "mkdir stuck; touch stuck/file; chmod 555 stuck",
                  'echo "gitdir: $PROJECT/.git" > .git',
                  "true")
        self.home.write(f".agentkit/env/{rig.name}.env", f"PROJECT={rig.path}\n")
        checks = [self.home.root / f"left-{index}" for index in range(len(messes))]
        for seen, mess in zip(checks, messes):
            self.add(rig, "fix-ui", seen.name, f"bash check.sh {seen} {shlex.quote(mess)}")
        # staged in the seat's checkout, its file as committed: only a reset of that index loses it
        (rig.path / "a").write_text("staged\n")
        rig.git("add", "a")
        (rig.path / "a").write_text("a\n")
        self.assertEqual(self.ak(rig, "fix-ui", "plan").code, 0)
        first, *rest = (seen.read_text() for seen in checks)
        self.assertEqual(rest, [first] * len(rest))
        self.assertEqual(rig.git("show", ":a"), "staged")


class TheCheckRunsOnOriginsDefaultBranch(PlanHome):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        home = cls.home
        cls.rig = rig = cls.project("fix-api", "acme")
        rig.commit({"local.txt": "only here\n"}, "on main, never pushed", push=False)
        rig.git("checkout", "-q", "-b", "work")
        rig.commit({"feature.txt": "the work\n"}, "the work, on its branch", push=False)
        (rig.path / "fixed.txt").write_text("uncommitted\n")
        # someone else lands on main: the seat's checkout has not fetched it
        other = home.root / "other"
        home.run("git", "clone", "-q", str(rig.bare), str(other))
        (other / "landed.txt").write_text("landed\n")
        for args in (("add", "-A"), ("commit", "-q", "-m", "landed"), ("push", "-q")):
            done = home.run("git", "-C", str(other), *args)
            assert done.code == 0, done.err
        cls.main = rig.head()

    def test_a_check_failing_there_is_written_naming_the_commit_it_failed_on(self):
        line = self.add(self.rig, "fix-api", "fixed exists",
                        'test -f fixed.txt && test -z "$AGENTKIT_SESSION$AK_RUN_ROLE"',
                        env={"AK_RUN_ROLE": "x"})
        self.assertEqual(LINE.fullmatch(line)["base"], self.main[:12])

    def test_what_only_the_seats_checkout_holds_is_not_there(self):
        for name in ("fixed.txt", "feature.txt", "local.txt"):
            with self.subTest(name):
                self.add(self.rig, "fix-api", f"{name} exists", f"test -f {name}")
                self.refused(self.rig, "fix-api", f"{name} missing", f"test ! -f {name}")

    def test_what_landed_on_origin_is_there_before_the_seat_pulls_it(self):
        self.refused(self.rig, "fix-api", "landed exists", "test -f landed.txt")

    def test_the_check_runs_without_aks_or_gits_own_variables(self):
        elsewhere = self.home.root / "elsewhere"
        self.refused(self.rig, "fix-api", "nothing leaks",
                     'test -z "$AGENTKIT_SESSION$AGENTKIT_TMUX_SOCKET$AK_RUN_ROLE$AK_RUN_DEPTH'
                     '$AK_NOTIFY_SINK$GIT_DIR$GIT_WORK_TREE$GIT_INDEX_FILE"',
                     env={"AK_RUN_ROLE": "x", "GIT_DIR": str(elsewhere / ".git"),
                          "GIT_WORK_TREE": str(elsewhere),
                          "GIT_INDEX_FILE": str(elsewhere / "index")})


class TheCheckSeesTheProjectsEnvFile(PlanHome):
    def env_file(self, rig, text):
        self.home.write(f".agentkit/env/{rig.name}.env", text)

    def test_its_variables_decide_whether_the_check_fails(self):
        rig = self.project("fix-api", "acme")
        self.refused(rig, "fix-api", "flag off", 'test "$ACME_FLAG" != on')
        self.env_file(rig, "# acme's test settings\nACME_FLAG=on\n")
        self.add(rig, "fix-api", "flag off", 'test "$ACME_FLAG" != on')

    def test_a_line_ticks_once_the_env_file_lets_its_check_pass(self):
        rig = self.project("fix-ui", "beta")
        line = self.add(rig, "fix-ui", "fast mode", 'test "$BETA_MODE" = fast')
        self.env_file(rig, "BETA_MODE=fast\n")
        self.assertEqual(self.ak(rig, "fix-ui", "plan").code, 0)
        self.assertEqual(self.plan("fix-ui"), [
            line.replace("- [ ] ", "- [x] ", 1) + f" · done {rig.head()[:12]} init"])


class APlanTicksOnTheDefaultBranch(PlanHome):
    HAND = ["- [x] hand kept", "- [ ] hand open", "free text"]

    def test_a_line_ticks_once_its_check_passes_there_and_hand_lines_stay(self):
        rig = self.project("fix-api", "acme")
        line = self.add(rig, "fix-api", "done exists", "test -f done.txt")
        path = self.home.path / ".agentkit" / "state" / "plan-fix-api.md"
        path.write_text(path.read_text() + "".join(f"{hand}\n" for hand in self.HAND))
        # the work on the seat's branch, pushed, and in its checkout: not yet on main
        rig.git("checkout", "-q", "-b", "work")
        rig.commit({"done.txt": "done\n"}, "add done on work")
        (rig.path / "done.txt").write_text("done, uncommitted\n")
        self.assertEqual(self.ak(rig, "fix-api", "plan").code, 0)
        self.assertEqual(self.plan("fix-api"), [line, *self.HAND])
        rig.git("checkout", "-q", "-f", "main")
        sha = rig.commit({"done.txt": "done\n"}, "add done")
        self.assertEqual(self.ak(rig, "fix-api", "plan").code, 0)
        ticked = line.replace("- [ ] ", "- [x] ", 1) + f" · done {sha[:12]} add done"
        self.assertEqual(self.plan("fix-api"), [ticked, *self.HAND])

    def test_the_default_branch_is_the_one_origin_names(self):
        rig = self.project("fix-ui", "beta")
        rig.git("push", "-q", "origin", "main:trunk")
        rig.origin("symbolic-ref", "HEAD", "refs/heads/trunk")
        rig.commit({"main.txt": "main only\n"}, "on main")
        line = self.add(rig, "fix-ui", "main.txt exists", "test -f main.txt")
        self.assertEqual(LINE.fullmatch(line)["base"], rig.head("trunk")[:12])
        self.assertEqual(self.ak(rig, "fix-ui", "plan").code, 0)
        self.assertEqual(self.plan("fix-ui"), [line])
        rig.git("push", "-q", "origin", "main:trunk")
        self.assertEqual(self.ak(rig, "fix-ui", "plan").code, 0)
        self.assertEqual(self.plan("fix-ui"), [
            line.replace("- [ ] ", "- [x] ", 1) + f" · done {rig.head('trunk')[:12]} on main"])


if __name__ == "__main__":
    unittest.main()
