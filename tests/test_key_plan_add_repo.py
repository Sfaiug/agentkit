"""A seat can check a plan line against a second repository's default branch."""

import unittest

from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig


class PlanAddRepo(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.primary = Rig(self.home, "acme")
        Seat(self.home, "fix-api", cwd=self.primary.path, record={"repo": str(self.primary.path)},
             alive=False)
        self.plan = self.home.path / ".agentkit/state/plan-fix-api.md"

    def ak(self, *args):
        return self.home.ak("plan", *args, cwd=self.primary.path, env={"AGENTKIT_SESSION": "fix-api"})

    def test_only_work_landed_in_the_named_checkout_ticks_the_line(self):
        helper = Rig(self.home, "helper", files={"README.md": "helper\n"})
        root = helper.head()[:12]
        base = helper.commit({"README.md": "helper service\n"})[:12]
        for target, flags in (
                ("api.txt", ("--repo", "~/code/helper", "--check", "test -f api.txt")),
                ("client.txt", ("--check", "test -f client.txt", "--repo", str(helper.path)))):
            done = self.ak("add", target, *flags)
            self.assertEqual(done.code, 0, done.err)
        opened = self.plan.read_text().splitlines()
        self.assertEqual(len(opened), 2)
        files = {"api.txt": "", "client.txt": ""}
        for target, line in zip(files, opened):
            self.assertTrue(line.startswith(f"- [ ] {target} · check: `test -f {target}` · "
                                            f"~/code/helper#{root} · written "), line)
            self.assertTrue(line.endswith(f" on {base}"), line)

        self.primary.commit(files)
        done = self.ak()
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.plan.read_text().splitlines(), opened)
        commit = helper.commit(files, "deliver files")[:12]
        done = self.ak()
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.plan.read_text().splitlines(),
                         [line.replace("[ ]", "[x]", 1) + f" · done {commit} deliver files"
                          for line in opened])

    def test_checkout_aliases_use_the_project_environment_when_adding(self):
        helper = Rig(self.home, "helper", files={"src/keep.txt": ""})
        alias = self.home.path / "service"
        alias.symlink_to(helper.path, target_is_directory=True)
        self.home.write(".agentkit/env/helper.env", "HELPER_READY=1\n")
        for path in (alias, helper.path / "src" / ".."):
            with self.subTest(path=path):
                done = self.ak("add", "helper is ready", "--repo", str(path),
                               "--check", 'test "$HELPER_READY" = 1')
                self.assertEqual(done.code, 2, done.err)
                self.assertIn("already passes on helper's default branch", done.err)
                self.assertFalse(self.plan.exists())

    def test_repo_must_be_a_checkout(self):
        for path in (self.home.path / "code", self.home.path / "missing", self.home.path / ("a" * 300)):
            with self.subTest(path=path):
                done = self.ak("add", "fix api", "--check", "false", "--repo", str(path))
                self.assertEqual(done.code, 2, done.err)
                self.assertIn(str(path), done.err)
                self.assertFalse(self.plan.exists())

    def test_invalid_flags_print_usage(self):
        repo = str(self.primary.path)
        for flags in (("--repo", repo), ("--check", "false", "--repo"),
                      ("--repo", repo, "--check"), ("--check", "--repo"),
                      ("--repo", repo, "--repo", repo), ("--check", "false", "--check", "false"),
                      ("--check", "false", "--repo", repo, "extra")):
            with self.subTest(flags=flags):
                done = self.ak("add", "fix api", *flags)
                self.assertEqual(done.code, 2, done.err)
                self.assertIn("usage: ak plan", done.err)
                self.assertFalse(self.plan.exists())


if __name__ == "__main__":
    unittest.main()
