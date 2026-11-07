"""The suite helper's image unpacks the Go release go/go.mod's toolchain line names only when its
sha256 is the one go/toolchain.sha256 lists for that file name (tools/helper/go.sh), and that list
names the release for each machine the image runs on.

    python3 tests/test_go_toolchain_fetch.py
"""

import functools
import hashlib
import http.server
import io
import os
import re
import subprocess
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FETCH = REPO / "tools" / "helper" / "go.sh"
# As dpkg names them: a server's, and the owner's M4's under Apple's container tool.
ARCHES = ("amd64", "arm64")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def release(version):
    """A gzipped tar laid out as a Go release: go/VERSION holding `version`."""
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        member = tarfile.TarInfo("go/VERSION")
        member.size = len(version)
        tar.addfile(member, io.BytesIO(version.encode()))
    return data.getvalue()


class Fetch(unittest.TestCase):
    def fetch(self, toolchain, listed, served, arch="amd64"):
        """go.sh's exit, what it printed and the files it unpacked, for go.mod's toolchain line
        naming `toolchain` on an `arch` machine, `listed` {file name: archive} the list's sha256s
        and `served` {file name: archive} what the loopback server holds."""
        with tempfile.TemporaryDirectory(prefix="ak-go-fetch-") as directory:
            root = Path(directory)
            for name in ("go", "served", "into", "bin", "tmp"):
                (root / name).mkdir()
            (root / "go/go.mod").write_text(f"module acme\n\ngo 1.23.0\n\ntoolchain {toolchain}\n")
            (root / "go/toolchain.sha256").write_text("".join(
                f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in listed.items()))
            for name, data in served.items():
                (root / "served" / name).write_bytes(data)
            dpkg = root / "bin/dpkg"
            dpkg.write_text(f"#!/bin/sh\necho {arch}\n")
            dpkg.chmod(0o755)
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0), functools.partial(Quiet, directory=root / "served"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                # Its own HOME, so no ~/.curlrc, and TMPDIR, so the download stays in here; no
                # proxy between curl and loopback.
                env = {**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
                       "HOME": str(root), "TMPDIR": str(root / "tmp"), "no_proxy": "*"}
                done = subprocess.run(
                    ["sh", str(FETCH), f"http://127.0.0.1:{server.server_port}", str(root / "go"),
                     str(root / "into")], env=env, capture_output=True, text=True)
            finally:
                server.shutdown()
                server.server_close()
            unpacked = {str(path.relative_to(root / "into")): path.read_text()
                        for path in (root / "into").rglob("*") if path.is_file()}
            self.assertEqual(list((root / "tmp").iterdir()), [], "go.sh leaves its download")
            return done.returncode, done.stderr, unpacked

    def test_the_listed_release_is_unpacked_on_each_machine(self):
        for arch in ARCHES:
            with self.subTest(arch=arch):
                name = f"go1.99.0.linux-{arch}.tar.gz"
                archive = {name: release("go1.99.0")}
                code, printed, unpacked = self.fetch("go1.99.0", archive, archive, arch)
                self.assertEqual((code, unpacked), (0, {"go/VERSION": "go1.99.0"}), printed)

    def test_anything_else_is_refused_and_nothing_unpacked(self):
        name = "go1.99.0.linux-amd64.tar.gz"
        listed = {name: release("go1.99.0")}
        # One byte of the gzip header's modification time: unchecked, it unpacks just the same.
        changed = bytearray(listed[name])
        changed[4] ^= 1
        for case, toolchain, served, refused in (
                ("one byte changed", "go1.99.0", {name: bytes(changed)}, name),
                ("a release the list does not name", "go1.99.1",
                 {"go1.99.1.linux-amd64.tar.gz": release("go1.99.1")},
                 "go1.99.1.linux-amd64.tar.gz"),
                ("a download that fails", "go1.99.0", {}, name)):
            with self.subTest(case):
                code, printed, unpacked = self.fetch(toolchain, listed, served)
                self.assertNotEqual(code, 0, printed)
                self.assertEqual(unpacked, {})
                self.assertIn(refused, printed)

    def test_the_repository_lists_the_toolchain_release_for_each_machine(self):
        toolchain = re.search(r"^toolchain (\S+)$", (REPO / "go/go.mod").read_text(), re.M)[1]
        lines = (REPO / "go/toolchain.sha256").read_text().splitlines()
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}  \S+", line) for line in lines), lines)
        self.assertEqual(sorted(line.split()[1] for line in lines),
                         [f"{toolchain}.linux-{arch}.tar.gz" for arch in ARCHES],
                         "go/toolchain.sha256 lists go.dev's sha256 of each, the toolchain line's"
                         " release and nothing else")


if __name__ == "__main__":
    unittest.main(verbosity=2)
