"""A Linux suite helper keeps a user's images in a repository of that user's own, as every user of
the machine's docker sees all its images: a `prepare` drops the other images of its own repository
and none of another user's, nor of an ak from before a user had its own, whose suite may need it.

Black-box, on the machine of tests/fixtures/akmachine.py: tools/helper's script as ak sends it, a
recipe alone its parcel.
"""

import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akmachine
from fixtures.akbin import Home

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "helper"
RECIPE = b"FROM docker.io/library/alpine:3.20\n"
MINE = f"{os.getuid()}-{os.getgid()}/ak-helper-widgets"
OTHERS = ["7-7/ak-helper-widgets:old", "ak-helper-widgets:old"]    # another user's, an earlier ak's


class AMachinesUserDropsOnlyItsOwnImages(unittest.TestCase):
    def test_a_prepare_leaves_the_images_of_no_repository_but_its_user_s(self):
        home = Home()
        self.addCleanup(home.close)
        images = akmachine.install(home) / "docker/images"
        for name in (*OTHERS, f"{MINE}:old"):
            (images / name).parent.mkdir(exist_ok=True)
            (images / name).touch()
        parcel = io.BytesIO()
        with tarfile.open(fileobj=parcel, mode="w") as tar:
            info = tarfile.TarInfo("image/Containerfile")
            info.size = len(RECIPE)
            tar.addfile(info, io.BytesIO(RECIPE))
        script = (TOOLS / "linux.sh").read_text() + (TOOLS / "mac.sh").read_text()
        prepare = subprocess.run(
            [home.bin / "ssh", "acme-linux", shlex.join([
                "bash", "-c", script, "mac.sh", "prepare", "key", "ak-helper-widgets:new",
                "widgets"])], input=parcel.getvalue(), capture_output=True, timeout=60)
        self.assertEqual(prepare.returncode, 3, prepare.stderr)    # 3: no history sent
        self.assertEqual(sorted(str(path.relative_to(images)) for path in images.rglob("*:*")),
                         sorted([*OTHERS, f"{MINE}:new"]))


if __name__ == "__main__":
    unittest.main()
