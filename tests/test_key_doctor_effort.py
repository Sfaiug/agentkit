"""`ak doctor` names each model set to an effort it does not take, and leaves the config alone.

What a model may run at comes from its harness: the adapter's live `models` listing first, else
the manifest's `[catalog."<model>"] efforts`, else its `[effort] levels`.  A model set outside
them would be launched at an effort its harness refuses or quietly replaces, so doctor names the
effort key, the model and the effort asked for; the owner chose it, and doctor never rewrites
it.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
with a config from akconfig.py and the echo adapter of tests/fixtures/adapters.
"""

import shlex
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REPO, Home

ECHO = REPO / "tests" / "fixtures" / "adapters"
# echo's adapter with a live `models` verb, which the fixture's own script has not
LISTING = """#!/bin/sh
if [ "$1" = models ]; then printf 'echo-1\\tEcho 1\\tlow medium\\n'; exit 0; fi
exec {script} "$@"
"""
LIMITS = '\n[effort]\nlevels = ["low", "high"]\n\n[catalog."echo-2"]\nefforts = ["none"]\n'
FITS = "effort  every model takes the effort it is set to"


class DoctorEffort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def adapters(self, name, *, script=None, manifest=""):
        """A directory of echo's adapter, its script or manifest changed as the test says."""
        root = self.home.root / f"adapters-{name}"
        root.mkdir()
        (root / "echo.toml").write_text((ECHO / "echo.toml").read_text() + manifest)
        if script is None:
            shutil.copy(ECHO / "echo.sh", root / "echo.sh")
        else:
            (root / "echo.sh").write_text(script)
            (root / "echo.sh").chmod(0o755)
        return {"AGENTKIT_ADAPTER_DIR": str(root)}

    def doctor(self, env, models):
        config = akconfig.write(self.home, models)
        before = config.read_bytes()
        done = self.home.ak("doctor", env=env)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(config.read_bytes(), before)
        return done.out.splitlines()

    def test_a_role_effort_the_listing_does_not_offer_is_named_and_kept(self):
        script = LISTING.format(script=shlex.quote(str(ECHO / "echo.sh")))
        env = self.adapters("listing", script=script)
        lines = self.doctor(env, {"echo": {"harness": "echo", "model": "echo-1",
                                           "effort": "low", "review_effort": "ultra"}})
        self.assertIn("review_effort  echo: echo-1 takes low medium, not ultra", lines)
        self.assertNotIn(FITS, lines)

    def test_the_manifest_levels_and_catalog_limit_each_model_and_each_is_named(self):
        env = self.adapters("limits", manifest=LIMITS)
        lines = self.doctor(env, {
            "one": {"harness": "echo", "model": "echo-1", "effort": "xhigh",
                    "exec_effort": "max"},
            "two": {"harness": "echo", "model": "echo-2", "effort": "high"}})
        for key, model, bad in (("effort", "one", "xhigh"), ("exec_effort", "one", "max"),
                                ("effort", "two", "high")):
            with self.subTest(key=key, model=model):
                self.assertTrue([line for line in lines if line.startswith(f"{key}  {model}: ")
                                 and line.endswith(f", not {bad}")], lines)
        self.assertNotIn(FITS, lines)

    def test_with_every_model_inside_its_limits_doctor_says_so(self):
        env = self.adapters("fits", manifest=LIMITS)
        lines = self.doctor(env, {
            "one": {"harness": "echo", "model": "echo-1", "effort": "high",
                    "exec_effort": "low"},
            "two": {"harness": "echo", "model": "echo-2", "effort": "none"}})
        self.assertIn(FITS, lines)
        self.assertFalse([line for line in lines if ", not " in line], lines)


if __name__ == "__main__":
    unittest.main()
