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
        # the module's own files, as `go fmt ./...` reads them: never a vendored module's
        own = [str(path.relative_to(GO)) for path in GO.rglob("*.go")
               if path.relative_to(GO).parts[0] != "vendor"]
        self.assertEqual(self.check(gofmt, "-l", *own), "", "`go fmt ./...` formats these files")
        platforms = (("linux", "amd64"), ("darwin", "arm64"), ("windows", "amd64"))
        self.check("go", "vet", "./...", **judge)
        # Vetted for each platform, tests and all, before any test runs: a test file calling a
        # helper behind a build tag of its own compiles here and fails another platform's `go test`.
        for system, arch in platforms:
            self.check("go", "vet", "./...", GOOS=system, GOARCH=arch, **judge)
        # No deadline: a busy host only slows a package, and the landing's silence watch ends a
        # hung one and names it.
        self.check("go", "test", "-timeout", "0", "./...", **judge)
        with tempfile.TemporaryDirectory(prefix="ak-go-") as out:
            for system, arch in platforms:
                self.check("go", "build", "-o", os.path.join(out, system), "./cmd/ak",
                           GOOS=system, GOARCH=arch, **judge)


if __name__ == "__main__":
    unittest.main(verbosity=2)
