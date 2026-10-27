"""On a red gate `ak update` puts Muse back from its snapshot, byte for byte.

Muse's channel installer deletes the build it replaces and offers no versioned reinstall, so the
only way back from a bad release is the snapshot ak takes of the install before it upgrades.  On
a red gate it restores that: the launcher, the old build's binary and its version and release
files as they were, with their modes, and the new build gone, then says Muse is back.  On green
the new build stays, as it does when the checks it failed fail on the old build too.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a Muse install laid out as its channel installer leaves one (a
launcher beside `muse-bin-<build>` and `.muse-version`, reached through a link on PATH), with
the gates stood in for by tests/fixtures/akgates.py.
"""

import hashlib
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akgates import Gates

OLD, NEW = "1.4.1-R4503.1", "1.4.1-R4600.1"
BUILD = '#!/bin/sh\necho "Muse Code 1.4.1"\necho "build {build}"\n'
# Asked to install, as its channel installer is, it swaps the build in place and deletes the
# old one; asked anything else, it runs the build `.muse-version` names.
LAUNCHER = r"""#!/bin/sh
here=$(dirname "$(readlink -f "$0")")
if [ "$MUSE_LAUNCHER_INSTALL" = 1 ]; then
  rm -f "$here/muse-bin-$(cat "$here/.muse-version")"
  printf '#!/bin/sh\necho "Muse Code 1.4.1"\necho "build %s"\n' {new} >"$here/muse-bin-{new}"
  chmod 750 "$here/muse-bin-{new}"
  echo {new} >"$here/.muse-version"
  echo '{{"version": "{new}"}}' >"$here/.muse-release-info.json"
  exit 0
fi
exec "$here/muse-bin-$(cat "$here/.muse-version")" "$@"
"""


class MuseSnapshot(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["spark"])
        self.gates = Gates(self.home)
        self.install = self.home.root / "muse"
        self.install.mkdir()
        files = {"muse-launcher": (LAUNCHER.format(new=NEW), 0o755),
                 f"muse-bin-{OLD}": (BUILD.format(build=OLD), 0o711),
                 ".muse-version": (OLD + "\n", 0o640),
                 ".muse-release-info.json": (json.dumps({"version": OLD}), 0o600)}
        for name, (text, mode) in files.items():
            (self.install / name).write_text(text)
            (self.install / name).chmod(mode)
        entry = self.home.bin / "muse"
        entry.unlink()
        entry.symlink_to(self.install / "muse-launcher")
        self.before = self.files()

    def files(self):
        """Each file of the install: its bytes' digest and its mode."""
        return {path.name: (hashlib.sha256(path.read_bytes()).hexdigest(),
                            oct(path.stat().st_mode & 0o7777))
                for path in sorted(self.install.iterdir())}

    def test_a_red_gate_restores_the_install_as_it_was(self):
        self.gates.exit("live", 1)
        done = self.home.ak("update", timeout=120)
        said = done.out + done.err
        self.assertEqual(done.code, 1, said)
        self.assertEqual(self.gates.ran(), ["live"])
        self.assertEqual(self.files(), self.before)
        self.assertEqual(Path(self.home.bin / "muse").readlink(), self.install / "muse-launcher")
        self.assertRegex(said, rf"(?m)^update: muse: reverted\b.*{OLD}")
        version = self.home.run("muse", "--version")
        self.assertEqual((version.code, version.out.split()[-1]), (0, OLD))

    def test_a_green_gate_keeps_the_new_build(self):
        done = self.home.ak("update", timeout=120)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((self.install / ".muse-version").read_text().strip(), NEW)
        self.assertEqual(sorted(self.files()), sorted(
            [".muse-release-info.json", ".muse-version", "muse-launcher", f"muse-bin-{NEW}"]))
        self.assertRegex(done.out + done.err, rf"(?m)^update: muse: upgraded\b.*{NEW}")

    def test_checks_failing_on_the_old_build_too_install_the_new_one_again(self):
        # the restore used the snapshot up: a new one is taken before installing again
        self.gates.exit("live", 1, ["d"], run=1)
        self.gates.exit("live", 1, ["d"], run=2)
        done = self.home.ak("update", timeout=120)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((self.install / ".muse-version").read_text().strip(), NEW)
        self.assertIn(f"muse-bin-{NEW}", self.files())


if __name__ == "__main__":
    unittest.main()
