"""A config.toml or harness manifest nested past Python's stack is refused like any file ak cannot
read: exit 2 and one line naming it, never a traceback.

tomllib reads an array inside an array by recursion, so past the recursion limit it raises
RecursionError where a file that is not TOML raises ValueError; each reader of the file must hold
both.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
and this test fails against `/bin/false`.
"""

import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REPO, Home

DEEP = "value = " + "[" * 1000 + "0" + "]" * 1000 + "\n"    # Python's default limit: 1000 frames


class TomlPastTheStack(unittest.TestCase):
    def refused(self, path, *commands, env=None):
        path.write_text(DEEP)
        for command in commands:
            with self.subTest(path.name, command=" ".join(command)):
                done = self.home.ak(*command, env=env)
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertTrue(done.err.startswith(f"ak {command[0]}: {path}: "), done.err)
                self.assertEqual(done.err.count("\n"), 1, done.err)

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def test_a_config_toml_too_deep_is_named(self):
        self.refused(self.home.path / ".agentkit" / "config.toml", ("usage", "--json"),
                     ("run", "status"))

    def test_a_manifest_too_deep_is_named(self):
        adapters = self.home.root / "adapters"
        adapters.mkdir()
        for file in ("echo.sh", "echo.toml"):
            shutil.copy(REPO / "tests" / "fixtures" / "adapters" / file, adapters / file)
        self.refused(adapters / "echo.toml", ("usage", "--json"), ("doctor",),
                     env={"AGENTKIT_ADAPTER_DIR": str(adapters)})


if __name__ == "__main__":
    unittest.main()
