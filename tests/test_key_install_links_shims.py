"""Every install links each seat guard (`tools/<name>-shim`) as `~/.agentkit/bin/<name>`, the
directory first on a seat's PATH, so a guard an update adds covers the seats already open and a
link left pointing elsewhere is repointed.  Black-box: install.sh of the checkout `AK_BIN` names
runs from outside in a Home of tests/fixtures/akbin.py, the host's tools the refusing fakes of
tests/fixtures/installer.py.
"""

import os
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home


class InstallLinksShims(unittest.TestCase):
    def test_every_shim_is_linked_and_a_stale_link_repointed(self):
        with Home() as home:
            installer.prepare(home)
            guards = home.path / ".agentkit" / "bin"
            guards.mkdir(parents=True)
            (guards / "ssh").symlink_to(home.path / "old-checkout" / "tools" / "ssh-shim")
            done = installer.run(home)
            self.assertEqual(done.code, 0, done.out + done.err)
            shims = sorted((installer.CHECKOUT / "tools").glob("*-shim"))
            self.assertIn("ssh-shim", [shim.name for shim in shims])
            for shim in shims:
                with self.subTest(shim.name):
                    link = guards / shim.name[:-len("-shim")]
                    self.assertEqual(Path(os.path.realpath(link)), shim.resolve())


if __name__ == "__main__":
    unittest.main()
