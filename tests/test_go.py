"""Go's ak in go/: formatted, vetted, its own tests passing, and built for every platform it ships on."""

import os
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
        if not shutil.which("go"):
            self.skipTest("go is not installed: Go 1.23 or newer builds go/")
        # gofmt ships beside go, which PATH may reach only through a link.
        gofmt = Path(shutil.which("go")).resolve().with_name("gofmt")
        self.assertEqual(self.check(gofmt, "-l", "."), "", "gofmt -w these files")
        self.check("go", "vet", "./...")
        self.check("go", "test", "./...")
        with tempfile.TemporaryDirectory(prefix="ak-go-") as out:
            for system, arch in (("linux", "amd64"), ("darwin", "arm64"), ("windows", "amd64")):
                self.check("go", "build", "-o", os.path.join(out, system), "./cmd/ak",
                           GOOS=system, GOARCH=arch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
