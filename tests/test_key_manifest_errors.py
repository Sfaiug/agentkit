"""A harness manifest (adapters/<harness>.toml) that is not TOML is refused naming its file, and
one missing from AGENTKIT_ADAPTER_DIR is read from the checkout's adapters/ instead.

Everything ak knows about a harness's screen, models and efforts is in its manifest, so a typo
there must say which file to fix, as a user error and never a traceback.  A directory of fake
adapters replaces the scripts that call models, not that knowledge: a harness it leaves out
keeps the manifest the checkout ships, and one it holds is read in place of the shipped one.
`ak doctor` shows which was read: it names a model set to an effort its manifest's catalog
does not give it, with the efforts that catalog does.  No adapter script of a real harness runs
here.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
and this test fails against `/bin/false`.
"""

import re
import shutil
import sys
from pathlib import Path
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REPO, Home
from fixtures import akconfig

FIXTURE_ADAPTERS = REPO / "tests" / "fixtures" / "adapters"


def adapter_dir(home, name):
    """A directory of fake adapters holding only the echo fixture's pair."""
    root = home.root / name
    root.mkdir()
    for file in ("echo.sh", "echo.toml"):
        shutil.copy(FIXTURE_ADAPTERS / file, root / file)
    return root


def shipped_model():
    """The first harness the checkout ships a manifest for whose catalog gives a model its
    efforts, and that model: (harness, model, efforts)."""
    for path in sorted((REPO / "adapters").glob("*.toml")):
        catalog = tomllib.loads(path.read_text()).get("catalog") or {}
        for model, entry in catalog.items():
            if isinstance(entry, dict) and entry.get("efforts"):
                return path.stem, model, entry["efforts"]
    raise AssertionError("the checkout ships no manifest whose catalog gives efforts")


class BrokenManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.adapters = adapter_dir(cls.home, "adapters")
        cls.manifest = cls.adapters / "echo.toml"
        cls.manifest.write_text(cls.manifest.read_text() + "[effort\n")
        cls.env = {"AGENTKIT_ADAPTER_DIR": str(cls.adapters)}

    def test_usage_refuses_a_manifest_that_is_not_toml_naming_its_file(self):
        done = self.home.ak("usage", "--json", env=self.env)
        self.assertEqual(done.code, 2, done.out)
        self.assertTrue(done.err.startswith(f"ak usage: {self.manifest}: "), done.err)
        self.assertNotIn("Traceback", done.err)
        self.assertEqual(done.out, "")

    def test_doctor_refuses_it_the_same_way(self):
        done = self.home.ak("doctor", env=self.env)
        self.assertEqual(done.code, 2, done.out)
        self.assertTrue(done.err.startswith(f"ak doctor: {self.manifest}: "), done.err)
        self.assertNotIn("Traceback", done.err)


class MissingManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.harness, cls.model, cls.efforts = shipped_model()
        # an effort no catalog gives, so doctor names the model with the efforts it read
        akconfig.write(cls.home, {"beta": {"harness": cls.harness, "model": cls.model,
                                           "effort": "turbo"}})

    def doctor(self, adapters):
        done = self.home.ak("doctor", env={"AGENTKIT_ADAPTER_DIR": str(adapters)})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.err, "")
        named = [line for line in done.out.splitlines() if re.search(r"\bbeta\b", line)]
        self.assertEqual(len(named), 1, done.out)
        self.assertIn(self.model, named[0])
        self.assertIn("turbo", named[0])
        return named[0]

    def takes(self, efforts):
        return re.compile(rf"(?<![\w-]){re.escape(' '.join(efforts))}(?![\w-]| \w)")

    def test_a_harness_the_adapter_dir_leaves_out_reads_the_checkouts_manifest(self):
        self.assertFalse((adapter_dir(self.home, "only-echo") / f"{self.harness}.toml").exists())
        line = self.doctor(self.home.root / "only-echo")
        self.assertRegex(line, self.takes(self.efforts))

    def test_a_manifest_the_adapter_dir_holds_is_read_in_place_of_the_checkouts(self):
        adapters = adapter_dir(self.home, "own-manifest")
        own = ["low"] if self.efforts != ["low"] else ["medium"]
        (adapters / f"{self.harness}.toml").write_text(
            f'version = 1\n\n[catalog]\n"{self.model}" = {{ label = "Beta", '
            f'efforts = ["{own[0]}"] }}\n')
        line = self.doctor(adapters)
        self.assertRegex(line, self.takes(own))
        self.assertNotRegex(line, self.takes(self.efforts))


if __name__ == "__main__":
    unittest.main()
