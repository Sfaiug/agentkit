"""Go's ak in go/: formatted, vetted, its own tests passing, and built for every platform it ships on.

    python3 tests/test_go.py [part ...]

Its parts are `fmt`, `vet <platform>` for the caller's own platform and each Go's ak ships on,
the module's tests, and `build <platform>` for each it ships on, a platform as Go names it
(`linux/amd64`); without arguments it checks each, in that order.
The module's tests take most of 15 minutes on a loaded host and one of them seconds, so each
failing part is named in the file FAILED_PARTS names, and every_file.py's re-run and each
narrowing step give it just those as its arguments: a Go test as `<package>.<Test>`, its
top-level test, runs alone in its package; a package as its import path runs whole; a step runs
by its name, on its platform wherever this runs.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from suite_shares import name_failed

GO = Path(__file__).resolve().parents[1] / "go"
# The landing suite reaches nothing beyond loopback: never fetch a toolchain or a module,
# so a go.mod asking for either fails here instead of hanging; one static binary, no C.
ENV = {**os.environ, "GOTOOLCHAIN": "local", "GOPROXY": "off", "CGO_ENABLED": "0"}
# Where Go's ak ships, each platform as `go tool dist list` names it.
PLATFORMS = ("linux/amd64", "darwin/arm64", "windows/amd64")


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


def step(part, gofmt, out, **judge):
    """As tested() a test's, the failing parts of the step `part` names, `fmt`, `vet <platform>`
    or `build <platform>`, and what it printed; None where it names none: on that platform
    wherever this runs, as a narrowing step may give a part on another host than the one that
    named it."""
    if part == "fmt":
        # the module's own files, as `go fmt ./...` reads them: never a vendored module's
        own = [str(path.relative_to(GO)) for path in GO.rglob("*.go")
               if path.relative_to(GO).parts[0] != "vendor"]
        done = run(gofmt, "-l", *own)
        # exiting 0, it names the files `go fmt ./...` would format
        found = done.stdout
    elif named := re.fullmatch(r"(vet|build) (\w+)/(\w+)", part):
        what, system, arch = named.groups()
        # Vetted tests and all; built as the one program Go's ak ships.
        target = ("./...",) if what == "vet" else ("-o", os.path.join(out, system), "./cmd/ak")
        done = run("go", what, *target, GOOS=system, GOARCH=arch, **judge)
        # vet's `-json`, a caller's GOFLAGS may ask, exits 0 printing an object a package, `{}`
        # where it finds nothing; what a build prints passing only informs (`-gcflags=-m`).
        found = what == "vet" and set(done.stdout.split()) - {"{}"}
    else:
        return None
    return [part] if done.returncode or found else [], done.stdout + done.stderr


def tested(part, **env):
    """The failing parts of the module's tests `part` names, and what they printed: a test
    alone in its package, else the package or pattern whole."""
    # A Go name holds no dot, nor does an import path of module agentkit; `./...` is every package.
    test = re.fullmatch(r"(.+)\.(\w+)", part)
    # No deadline: a busy host only slows a package, and the landing's silence watch ends a
    # hung one and names it.
    done = run("go", "test", "-json", "-timeout", "0",
               *(("-run", f"^{test[2]}$", test[1]) if test else (part,)), **env)
    # An event a line, split at LF alone: Go writes U+0085 into an Output string unescaped, a
    # line break to splitlines().
    events = [json.loads(line) for line in done.stdout.split("\n") if line]
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
        # JSON, the one format go env keeps whatever the caller's GOFLAGS (`-json`) ask.
        found = run("go", "env", "-json", "GOROOT", "GOOS", "GOARCH", **judge)
        self.assertEqual(found.returncode, 0, f"go env {judge}\n{found.stdout}{found.stderr}")
        goenv = json.loads(found.stdout)
        gofmt = Path(goenv["GOROOT"], "bin", "gofmt")
        host = f"{goenv['GOOS']}/{goenv['GOARCH']}"
        failed, shown = [], []
        with tempfile.TemporaryDirectory(prefix="ak-go-") as out:
            # Vetted for each platform, tests and all, before any test runs: a test file calling
            # a helper behind a build tag of its own compiles on one platform and fails another's
            # `go test`; first the caller's own, where its tests run, once where Go's ak ships on
            # it.  Every part runs whatever one before it did: a re-run of the failing ones alone
            # passes this file only where every other part has passed.
            for part in sys.argv[1:] or dict.fromkeys(
                    ["fmt", f"vet {host}", *(f"vet {name}" for name in PLATFORMS),
                     "./...", *(f"build {name}" for name in PLATFORMS)]):
                names, printed = step(part, gofmt, out, **judge) or tested(part, **judge)
                if names:
                    failed += names
                    shown.append(f"--- {' '.join(names)}\n{printed}")
        name_failed(failed, "FAILED_PARTS")
        self.assertFalse(failed, "".join(shown))


if __name__ == "__main__":
    # The parts are the test's own arguments, never unittest's.
    unittest.main(argv=sys.argv[:1], verbosity=2)
