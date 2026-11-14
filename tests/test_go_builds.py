"""Go's ak builds: `./cmd/ak` in go/, the program written outside the checkout.

A static check (suite_shares.STATIC_CHECKS): Go that does not build ends every piece of the
landing suite in seconds, named as this one file and the compiler's lines its output, before
tests/test_go_keys.py fails each of its claims on it.  That file builds as build() does, so its
build finds this one cached.
Offline: Go's own build of this checkout's go/, its modules vendored.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_go import ENV

GO = Path(__file__).resolve().parents[1] / "go"


def build(go, program):
    """Go's ak in the folder `go`, a go/ or a copy of it, built as `program`, and how it went.
    Trimmed, a build in one copy finds what a build in another cached."""
    return subprocess.run(["go", "build", "-o", program, "-trimpath", "./cmd/ak"], env=ENV, cwd=go,
                          capture_output=True, text=True)


class GoBuilds(unittest.TestCase):
    def builds(self, go):
        with tempfile.TemporaryDirectory(prefix="ak-go-builds-") as out:
            built = build(go, Path(out, "ak"))
        if built.returncode:
            self.fail(built.stderr)

    def test_go_builds(self):
        self.builds(GO)

    def test_go_that_does_not_compile_fails_with_the_compiler_s_line(self):
        with tempfile.TemporaryDirectory(prefix="ak-go-builds-") as tmp:
            go = Path(tmp, "go")
            shutil.copytree(GO, go, symlinks=True)
            # As two changes landing together left a name one used and the other had moved.
            (go / "cmd/ak/acme.go").write_text("package main\n\nvar _ = Waiting\n")
            with self.assertRaises(AssertionError) as failed:
                self.builds(go)
        self.assertIn("cmd/ak/acme.go:3:9: undefined: Waiting", str(failed.exception))


if __name__ == "__main__":
    unittest.main()
