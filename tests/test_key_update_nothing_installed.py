"""`ak update` with no harness to move upgrades nothing, runs no gate and says why.

An update's gate is hours of real model calls, so it runs only once a harness has moved.  A
harness this host lacks is a skipped line, not a failure, and with nothing installed and no
agentkit checkout to fast-forward the update ends 1 with nothing changed; a harness whose
manifest has no `[update]` recipe is left out of the plan without a word, and when no
configured one has a recipe the update refuses outright.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, with a config from akconfig.py and copies of
the echo adapter of tests/fixtures/adapters.
"""

from pathlib import Path
import re
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REPO, Home

ECHO = REPO / "tests" / "fixtures" / "adapters"
RECIPE = (ECHO / "echo.toml").read_text()
ABSENT = RECIPE.replace('version = ["echo", "1.0.0"]',
                        'version = ["ak-no-such-binary", "--version"]')
NO_RECIPE = re.sub(r"(?m)^\[update\]\n(?:.+\n)*", "", RECIPE)
NONE_SAYS = "no configured harness says how it is upgraded"


class UpdateNothingInstalled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert ABSENT != RECIPE and "[update]" not in NO_RECIPE, "echo.toml changed shape"
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def adapters(self, name, **manifests):
        """A directory of adapters, each harness the echo script beside the manifest given."""
        root = self.home.root / f"adapters-{name}"
        root.mkdir()
        for harness, text in manifests.items():
            (root / f"{harness}.toml").write_text(text)
            shutil.copy(ECHO / "echo.sh", root / f"{harness}.sh")
        return {"AGENTKIT_ADAPTER_DIR": str(root)}

    def files(self):
        """Every file under HOME and what it holds."""
        return {path: path.read_bytes() for path in self.home.path.rglob("*")
                if path.is_file() and not path.is_symlink()}

    def test_with_no_harness_installed_nothing_moves_and_it_exits_1(self):
        env = self.adapters("absent", echo=ABSENT)
        akconfig.write(self.home, {"echo": {"harness": "echo", "model": "echo-1"}})
        before = self.files()
        done = self.home.ak("update", env=env)
        self.assertEqual(done.code, 1, done.out + done.err)
        for line in ("update: echo: skipped: not installed here",
                     "update: no harness installed here; nothing to upgrade",
                     f"update: agentkit: skipped: no checkout at {self.home.path / 'agentkit'}"):
            self.assertIn(line, done.out.splitlines())
        self.assertIn("update: nothing was upgraded; the gate was not run", done.err.splitlines())
        self.assertEqual(self.files(), before)

    def test_the_dry_run_names_the_missing_harness_and_exits_0(self):
        env = self.adapters("absent-dry", echo=ABSENT)
        akconfig.write(self.home, {"echo": {"harness": "echo", "model": "echo-1"}})
        done = self.home.ak("update", "--dry-run", env=env)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("update: echo: skipped: not installed here", done.out.splitlines())
        self.assertTrue([line for line in done.out.splitlines()
                         if line.startswith("echo not installed (")], done.out)

    def test_with_no_upgrade_recipe_anywhere_it_refuses_with_2(self):
        env = self.adapters("no-recipe", echo=NO_RECIPE)
        akconfig.write(self.home, {"echo": {"harness": "echo", "model": "echo-1"}})
        for args in (("update", "--dry-run"), ("update",)):
            with self.subTest(args=args):
                done = self.home.ak(*args, env=env)
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertIn(NONE_SAYS, done.err)

    def test_a_harness_without_a_recipe_is_left_out_of_the_plan(self):
        env = self.adapters("mixed", echo=RECIPE, beta=NO_RECIPE)
        akconfig.write(self.home, {"one": {"harness": "echo", "model": "echo-1"},
                                   "two": {"harness": "beta", "model": "beta-1"}})
        done = self.home.ak("update", "--dry-run", env=env)
        self.assertEqual(done.code, 0, done.out + done.err)
        # a plan line starts with its harness's name; the gate lines print this checkout's path
        named = [line.split(" ")[0] for line in done.out.splitlines()]
        self.assertIn("echo", named)
        self.assertNotIn("beta", named)
        self.assertFalse([line for line in done.out.splitlines()
                          if line.startswith("update: beta:")], done.out)


if __name__ == "__main__":
    unittest.main()
