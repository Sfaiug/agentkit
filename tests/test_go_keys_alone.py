"""With AK_GO_ALONE=1 the answer keys judge Go as the commit switching ak to Go holds it: the copy
tests/test_go_keys.py's checkout() makes has no agentkit/, its bin/, hooks/, adapters/, tools/
and install.sh are go/'s, tools/ keeping the shell that commit keeps, its bin/ak the program
judged, and in tests/fixtures/akbin.py's Home the program can run no python3.  Without it the copy
and the Home are as before.  A claim is judged so unless go/leans/ names its key file, and with
AK_GO_ALONE=1 even then: a stand-in running python3 fails a claim judged so and passes one not."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_go_keys import KEPT, LEFT_OUT, REPO, checkout

PARTS = ("bin", "hooks", "adapters", "tools", "install.sh")
# A program leaning on Python, as one handing work to Python's ak would; it exits as python3 does.
STAND_IN = "#!/bin/sh\npython -c pass\npython3 -c pass\n"
# The stand-in run through a Home as a key runs it: its exit, and the calls the Home's fakes logged.
KEY = """import json, sys
sys.path.insert(0, sys.argv[1])
from fixtures.akbin import Home
with Home() as home:
    done = home.ak()
    print(json.dumps([done.code, home.calls("python"), home.calls("python3")]))
"""
# A key file the stand-in passes where it can run python3.
CLAIMED = """import unittest
from fixtures.akbin import Home
class StandIn(unittest.TestCase):
    def test_it_exits_0(self):
        with Home() as home:
            self.assertEqual(home.ak().code, 0)
unittest.main()
"""


def held(path):
    """What `path` holds, read through its links: a file's bytes, a folder's entries by name, and
    None for a link leading nowhere."""
    if path.is_dir():
        return {entry.name: held(entry) for entry in path.iterdir() if entry.name != "__pycache__"}
    return path.read_bytes() if path.exists() else None


class Alone(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="ak-go-alone-")))
        self.stand_in = folder / "stand-in"
        self.stand_in.write_text(STAND_IN)
        self.stand_in.chmod(0o755)
        # none of the caller's AK_GO_ALONE, nor any other switch of its own, nor the files
        # every_file.py has this file's parts named in
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("AGENTKIT_", "AK_"))
                    and key not in ("FAILED_PARTS", "PART_TIMES", "NOT_THERE")}
        self.env["AK_BIN"] = str(self.stand_in)

    def copy(self, **env):
        """checkout()'s copy, as a Path, and the program it judges, under `env`."""
        with patch.dict(os.environ, {**self.env, **env}, clear=True):
            tree, program, _built = self.enterContext(checkout(build=False))
        return Path(tree), program

    def test_the_copy_is_shaped_like_the_switch_commit(self):
        tree, program = self.copy(AK_GO_ALONE="1")
        self.assertEqual(program, tree / "bin/ak")
        self.assertFalse((tree / "agentkit").exists())
        want = {part: held(REPO / "go" / part) for part in PARTS}
        want["bin"] = {"ak": STAND_IN.encode()}
        # go/tools/ak leads to its checkout's program
        want["tools"]["ak"] = STAND_IN.encode()
        # and Python's tools/ leaves it the shell the switch keeps, a helper's scripts among it
        want["tools"].update({Path(name).name: held(REPO / name) for name in KEPT})
        self.assertEqual({part: held(tree / part) for part in PARTS}, want)

    def test_without_the_switch_the_copy_is_as_before(self):
        tree, program = self.copy()
        self.assertEqual(program, self.stand_in)
        self.assertFalse((tree / "agentkit").exists())
        self.assertEqual({part: held(tree / part) for part in PARTS},
                         {part: held(REPO / part) for part in PARTS})

    def test_the_program_can_run_no_python3_only_with_the_switch(self):
        refused = [1, [["-c", "pass"]], [["-c", "pass"]]]
        for env, want in (({"AK_GO_ALONE": "1"}, refused), ({}, [0, [], []])):
            with self.subTest(**env):
                done = subprocess.run([sys.executable, "-c", KEY, REPO / "tests"],
                                      env={**self.env, **env}, capture_output=True, text=True,
                                      timeout=120)
                self.assertEqual(json.loads(done.stdout or "null"), want, done.stderr)

    def test_a_claim_is_judged_switched_unless_go_leans_names_its_key_file(self):
        tip = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="ak-go-leans-")))
        shutil.copytree(REPO, tip, ignore=LEFT_OUT, symlinks=True, dirs_exist_ok=True)
        keys = ("test_key_fix_api", "test_key_widget")
        (tip / "go/keys.txt").write_text("".join(f"{key}\n" for key in keys))
        for key in keys:
            (tip / "tests" / f"{key}.py").write_text(CLAIMED)
        shutil.rmtree(tip / "go/leans", ignore_errors=True)
        (tip / "go/leans").mkdir()
        (tip / "go/leans/test_key_fix_api").touch()
        failed = self.stand_in.with_name("failed")
        for env, want in (({}, ["test_key_widget"]), ({"AK_GO_ALONE": "1"}, list(keys))):
            with self.subTest(**env):
                failed.unlink(missing_ok=True)
                done = subprocess.run([sys.executable, tip / "tests/test_go_keys.py", *keys],
                                      env={**self.env, **env, "FAILED_PARTS": str(failed)},
                                      capture_output=True, text=True, timeout=600)
                said = done.stdout + done.stderr
                self.assertEqual(sorted(failed.read_text().split()), want, said)
                # each judged once, and one failing switched says first that go/leans/ is why
                self.assertCountEqual(re.findall(r"^--- (\S+)$", done.stdout, re.M), keys, said)
                if not env:
                    self.assertRegex(done.stdout,
                                     re.compile(r"^--- test_key_widget\n.*go/leans/", re.M), said)


if __name__ == "__main__":
    unittest.main()
