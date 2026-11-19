"""The fake adapter's manifest names its state folders as they are written, a dollar included:
a manifest path is a template (`config.manifest_paths`), and a temporary folder may hold one."""

import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import config
from fixtures import fakeadapter
from fixtures.akbin import AK, Home


class Dollar(unittest.TestCase):
    def test_a_dollar_in_the_temporary_folder(self):
        with tempfile.TemporaryDirectory(prefix="ak-dollar-") as root:
            folder = Path(root, "literal $ ${ACME_HOME:-fallback}")
            folder.mkdir()
            with patch.object(tempfile, "tempdir", str(folder)), Home() as home:
                fake = fakeadapter.install(home, claude="work")["claude"]
                named = tomllib.loads(fake.manifest.read_text())["worker"]["state"]
                self.assertEqual(list(config.manifest_paths(named, home.env)),
                                 [fake.dir, Path(AK).parent])


if __name__ == "__main__":
    unittest.main()
