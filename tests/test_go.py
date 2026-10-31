"""Go's ak in go/: formatted, vetted, its own tests passing, and built for every platform it ships on."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

GO = Path(__file__).resolve().parents[1] / "go"
# The landing suite reaches nothing beyond loopback: never fetch a toolchain or a module,
# so a go.mod asking for either fails here instead of hanging; one static binary, no C.
ENV = {**os.environ, "GOTOOLCHAIN": "local", "GOPROXY": "off", "CGO_ENABLED": "0"}


class Go(unittest.TestCase):
    def check(self, *command, **env):
        result = subprocess.run(command, cwd=GO, env={**ENV, **env}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"{command} {env}\n{result.stdout}{result.stderr}")
        return result.stdout

    def test_formatted_vetted_tested_and_built(self):
        # Never a skip: the landing suite counts a skipped case as passed.
        self.assertTrue(shutil.which("go"), "go is not installed: Go 1.23 or newer builds go/")
        # Two releases' gofmt can lay one file out two ways and their vet judge it two ways, so
        # every machine judges with the release go.mod's toolchain line names: its own go, or
        # that release in go's cache, else this fails naming it.
        release = re.search(r"^toolchain (\S+)$", (GO / "go.mod").read_text(), re.M)
        self.assertTrue(release, "go/go.mod names no toolchain: the Go release that judges go/")
        judge = {"GOTOOLCHAIN": release[1]}
        gofmt = Path(self.check("go", "env", "GOROOT", **judge).strip(), "bin", "gofmt")
        self.assertEqual(self.check(gofmt, "-l", "."), "", "`go fmt ./...` formats these files")
        self.check("go", "vet", "./...", **judge)
        self.check("go", "test", "./...", **judge)
        with tempfile.TemporaryDirectory(prefix="ak-go-") as out:
            for system, arch in (("linux", "amd64"), ("darwin", "arm64"), ("windows", "amd64")):
                self.check("go", "build", "-o", os.path.join(out, system), "./cmd/ak",
                           GOOS=system, GOARCH=arch, **judge)


if __name__ == "__main__":
    unittest.main(verbosity=2)
