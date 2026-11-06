"""Go's ak in go/: formatted, vetted, its own tests passing, and built for every platform it ships on.

    python3 tests/test_go.py [part ...]

Its parts are `fmt`, `vet <platform>` for each platform Go's ak ships on, the module's tests,
and `build <platform>` for each platform; without arguments it checks each, in that order.
The module's tests take most of 15 minutes on a loaded host and one of them seconds, so each
failing part is named in the file FAILED_PARTS names, and every_file.py's re-run and each
narrowing step give it just those as its arguments: a Go test as `<package>.<Test>`, its
top-level test, runs alone in its package; a package as its import path runs whole; a step runs
by its name.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from functools import partial
from pathlib import Path

from suite_shares import name_failed

GO = Path(__file__).resolve().parents[1] / "go"
# The landing suite reaches nothing beyond loopback: never fetch a toolchain or a module,
# so a go.mod asking for either fails here instead of hanging; one static binary, no C.
ENV = {**os.environ, "GOTOOLCHAIN": "local", "GOPROXY": "off", "CGO_ENABLED": "0"}
# Where Go's ak ships: the architecture each system is built for.
PLATFORMS = {"linux": "amd64", "darwin": "arm64", "windows": "amd64"}


def run(*command, **env):
    # The caller's environment, its GOFLAGS among it, holds in every run.
    return subprocess.run(command, cwd=GO, env={**ENV, **env}, capture_output=True, text=True)


def about(event):
    """The part a `go test -json` event is about: its top-level test, else its package."""
    test = event.get("Test", "").partition("/")[0]
    return f"{event.get('Package')}.{test}" if test else event.get("Package")


def failing(events):
    """The parts `go test -json`'s events name as failing: each top-level test any of whose runs
    failed, so a test failing then passing under `-count=2` still is; each package whose test
    binary died, one of its tests started and never ended, or that failed with no test of its
    own failing, as one whose tests do not compile, naming none of its tests: run whole, it runs
    what they left unrun."""
    started = set()
    for event in events:
        ran = (event.get("Package"), event.get("Test"))
        if event["Action"] == "run":
            started.add(ran)
        elif event["Action"] in ("pass", "fail", "skip"):
            started.discard(ran)
    fails = [event for event in events if event["Action"] == "fail"]
    failed_tests = [event for event in fails if "Test" in event]
    whole = {package for package, _ in started} | (
        {event["Package"] for event in fails} - {event["Package"] for event in failed_tests})
    return sorted(whole | {about(event) for event in failed_tests if event["Package"] not in whole})


def tested(part, **env):
    """The failing parts of the module's tests `part` names, and what they printed: a test
    alone in its package, else the package or pattern whole."""
    # A Go name holds no dot, nor does an import path of module agentkit; `./...` is every package.
    test = re.fullmatch(r"(.+)\.(\w+)", part)
    # No deadline: a busy host only slows a package, and the landing's silence watch ends a
    # hung one and names it.
    done = run("go", "test", "-json", "-timeout", "0",
               *(("-run", f"^{test[2]}$", test[1]) if test else (part,)), **env)
    events = [json.loads(line) for line in done.stdout.splitlines()]
    # A run whose events name nothing that failed, as one go itself refused, fails as `part`.
    names = failing(events) or ([part] if done.returncode else [])
    if test and not names and part not in map(about, events):
        return [part], f"{part} is not there: no test of {test[1]} runs by that name\n"
    # Build output belongs to a package that failed to build.
    printed = "".join(event.get("Output", "") for event in events
                      if event["Action"] == "build-output"
                      or event.get("Package") in names or about(event) in names)
    return names, printed + done.stderr


class Go(unittest.TestCase):
    def test_formatted_vetted_tested_and_built(self):
        # Never a skip: the landing suite counts a skipped case as passed.
        self.assertTrue(shutil.which("go"), "go is not installed: Go 1.23 or newer builds go/")
        # Two releases' gofmt can lay one file out two ways and their vet judge it two ways, so
        # every machine judges with the release go.mod's toolchain line names: its own go, or
        # that release in go's cache, else this fails naming it.
        release = re.search(r"^toolchain (\S+)$", (GO / "go.mod").read_text(), re.M)
        self.assertTrue(release, "go/go.mod names no toolchain: the Go release that judges go/")
        judge = {"GOTOOLCHAIN": release[1]}
        found = run("go", "env", "GOROOT", **judge)
        self.assertEqual(found.returncode, 0, f"go env {judge}\n{found.stdout}{found.stderr}")
        root = found.stdout.strip()
        # the module's own files, as `go fmt ./...` reads them: never a vendored module's
        own = [str(path.relative_to(GO)) for path in GO.rglob("*.go")
               if path.relative_to(GO).parts[0] != "vendor"]
        failed, shown = [], []
        with tempfile.TemporaryDirectory(prefix="ak-go-") as out:
            # A step passes exiting 0 with nothing on its stdout, where `gofmt -l` names the
            # files `go fmt ./...` would format.
            steps = {"fmt": partial(run, Path(root, "bin", "gofmt"), "-l", *own),
                     **{f"vet {name}": partial(run, "go", "vet", "./...", GOOS=name, GOARCH=arch,
                                               **judge)
                        for name, arch in PLATFORMS.items()},
                     **{f"build {name}": partial(run, "go", "build", "-o", os.path.join(out, name),
                                                 "./cmd/ak", GOOS=name, GOARCH=arch, **judge)
                        for name, arch in PLATFORMS.items()}}
            # Vetted for each platform, tests and all, before any test runs: a test file calling
            # a helper behind a build tag of its own compiles here and fails another platform's
            # `go test`.  Every part runs whatever one before it did: a re-run of the failing
            # ones alone passes this file only where every other part has passed.
            for part in sys.argv[1:] or ["fmt", *(f"vet {name}" for name in PLATFORMS), "./...",
                                         *(f"build {name}" for name in PLATFORMS)]:
                if part in steps:
                    done = steps[part]()
                    names = [part] if done.returncode or done.stdout else []
                    printed = done.stdout + done.stderr
                else:
                    names, printed = tested(part, **judge)
                if names:
                    failed += names
                    shown.append(f"--- {' '.join(names)}\n{printed}")
        name_failed(failed, "FAILED_PARTS")
        self.assertFalse(failed, "".join(shown))


if __name__ == "__main__":
    # The parts are the test's own arguments, never unittest's.
    unittest.main(argv=sys.argv[:1], verbosity=2)
