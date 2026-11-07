"""A failing tests/test_go.py names what failed in the file FAILED_PARTS names, read from
`go test -json`'s events: a top-level test any of whose runs failed as `<package>.<Test>`; a
package whose test binary died, or that failed with no test of its own failing, by its import
path and none of its tests; a step by what it checks, the vet of the caller's own platform among
them, and each passing part's seconds in the file PART_TIMES names.  Given parts it runs just
those after the toolchain check, a step on its platform, a named test with no event failing as
not there, yet named and timed as no part, as it ran nowhere; without, every part in its order.
The caller's GOFLAGS hold in every run it makes; a vet fails by what it finds, shown, in text or
as the JSON they may ask, never by the `{}` of a package it finds nothing in, and a build by its
exit code alone, whatever it prints.

Offline: the real test_go.py runs with a fake `go` first on PATH, on the platform ACME_HOST
names, noting each call and its GOFLAGS, whose `test -json` prints the events a test hands it,
whatever it is asked.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
# A vet or build is noted by its platform, a build's output path being a temporary one; either
# fails where ACME_BROKEN names its call, a test run where its events hold a failure; either
# prints ACME_PRINTS.
GO = '''#!/bin/sh
case "$1" in
vet|build) call="go $1 $GOOS/$GOARCH" ;;
*) call="go $*" ;;
esac
echo "$call" >>"$ACME_LOG"
echo "$GOFLAGS" >>"$ACME_FLAGS"
case "$1" in
env) printf '{"GOROOT": "%s", "GOOS": "%s", "GOARCH": "%s"}\n' "$ACME_ROOT" "${ACME_HOST%/*}" "${ACME_HOST#*/}" ;;
test) cat "$ACME_EVENTS"; ! grep -q '"Action":"fail"' "$ACME_EVENTS" ;;
*) printf %s "$ACME_PRINTS"; case "$ACME_BROKEN" in *"$call"*) echo "$call broke" >&2; exit 1 ;; esac ;;
esac
'''
GOFMT = '''#!/bin/sh
echo "gofmt $1" >>"$ACME_LOG"
echo "$GOFLAGS" >>"$ACME_FLAGS"
printf %s "$ACME_UNFORMATTED"
'''
GOFLAGS = "-skip=TestWidget -count=2"
ACME, WIDGET = "agentkit/internal/acme", "agentkit/internal/widget"
TOOLCHAIN = "go env -json GOROOT GOOS GOARCH"
# Under GOFLAGS=-json vet exits 0 whatever it finds, printing an object a package, `{}` where it
# finds nothing; a passing build prints what its flags ask, as -gcflags=-m does.
CLEAN = "{}\n{}\n"
FOUND = '{"agentkit/internal/acme": {"printf": [{"posn": "acme.go:5:27", "message": "wrong type"}]}}\n'
BUILT = '{"ImportPath":"agentkit/cmd/ak","Action":"build-output","Output":"can inline main\\n"}\n'
# t.Fatal in a subtest ends its run `fail`, then its test's, then its package's.
FATAL = r'''{"Action":"start","Package":"agentkit/internal/acme"}
{"Action":"run","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"run","Package":"agentkit/internal/acme","Test":"TestFixApi/widget"}
{"Action":"output","Package":"agentkit/internal/acme","Test":"TestFixApi/widget","Output":"fix-api broke\n"}
{"Action":"fail","Package":"agentkit/internal/acme","Test":"TestFixApi/widget"}
{"Action":"fail","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"run","Package":"agentkit/internal/acme","Test":"TestWidget"}
{"Action":"pass","Package":"agentkit/internal/acme","Test":"TestWidget"}
{"Action":"fail","Package":"agentkit/internal/acme"}
{"Action":"pass","Package":"agentkit/internal/widget"}
'''
# -count=2: the first run fails, the second passes.
FLIPS = r'''{"Action":"run","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"output","Package":"agentkit/internal/acme","Test":"TestFixApi","Output":"first run broke\n"}
{"Action":"fail","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"run","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"output","Package":"agentkit/internal/acme","Test":"TestFixApi","Output":"second run fine\n"}
{"Action":"pass","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"fail","Package":"agentkit/internal/acme"}
'''
# acme's test binary dies in TestWidget after TestFixApi failed; widget's tests do not compile.
WHOLE = r'''{"Action":"run","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"fail","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"run","Package":"agentkit/internal/acme","Test":"TestWidget"}
{"Action":"output","Package":"agentkit/internal/acme","Test":"TestWidget","Output":"fatal error: concurrent map writes\n"}
{"Action":"fail","Package":"agentkit/internal/acme"}
{"ImportPath":"agentkit/internal/widget [agentkit/internal/widget.test]","Action":"build-output","Output":"undefined: fixApi\n"}
{"ImportPath":"agentkit/internal/widget [agentkit/internal/widget.test]","Action":"build-fail"}
{"Action":"fail","Package":"agentkit/internal/widget","FailedBuild":"agentkit/internal/widget [agentkit/internal/widget.test]"}
'''
# A passing test logs U+0085, which Go leaves unescaped inside its event's line.
PASSES = '''{"Action":"run","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"output","Package":"agentkit/internal/acme","Test":"TestFixApi","Output":"fix-api\u0085logged\\n"}
{"Action":"pass","Package":"agentkit/internal/acme","Test":"TestFixApi"}
{"Action":"pass","Package":"agentkit/internal/acme"}
{"Action":"pass","Package":"agentkit/internal/widget"}
'''


class GoNamesItsFailingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="ak-test-go-")))
        for path, body in (("bin/go", GO), ("goroot/bin/gofmt", GOFMT)):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(body)
            (self.root / path).chmod(0o755)

    def read(self, name):
        path = self.root / name
        return path.read_text().splitlines() if path.exists() else []

    def checked(self, *parts, events=PASSES, host="linux/arm64", **env):
        """test_go.py's run for `parts` on `host`: its exit code, output, named parts and calls."""
        (self.root / "events").write_text(events)
        for name in ("calls", "flags", "parts", "times"):
            (self.root / name).unlink(missing_ok=True)
        done = subprocess.run(
            [sys.executable, REPO / "tests/test_go.py", *parts],
            env=dict(os.environ, PATH=f"{self.root / 'bin'}{os.pathsep}{os.environ['PATH']}",
                     GOFLAGS=GOFLAGS, ACME_LOG=str(self.root / "calls"),
                     ACME_FLAGS=str(self.root / "flags"), ACME_ROOT=str(self.root / "goroot"),
                     ACME_EVENTS=str(self.root / "events"), FAILED_PARTS=str(self.root / "parts"),
                     PART_TIMES=str(self.root / "times"), ACME_HOST=host, **env),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        return done.returncode, done.stdout + done.stderr, self.read("parts"), self.read("calls")

    def test_a_failing_go_test_is_named_by_its_package_and_top_level_test(self):
        code, out, parts, _ = self.checked(events=FATAL)
        self.assertEqual((code, parts), (1, [f"{ACME}.TestFixApi"]), out)
        self.assertIn("fix-api broke", out)

    def test_a_test_failing_one_of_its_runs_is_named_and_shows_what_it_printed_failing(self):
        code, out, parts, _ = self.checked(events=FLIPS)
        self.assertEqual((code, parts), (1, [f"{ACME}.TestFixApi"]), out)
        self.assertIn("first run broke", out)

    def test_a_package_whose_binary_died_or_tests_do_not_compile_is_named_not_its_tests(self):
        code, out, parts, _ = self.checked(events=WHOLE)
        self.assertEqual((code, parts), (1, [ACME, WIDGET]), out)
        self.assertIn("fatal error: concurrent map writes", out)
        self.assertIn("undefined: fixApi", out)

    def test_a_failing_step_is_named_by_what_it_checks_and_every_part_still_runs(self):
        code, out, parts, calls = self.checked(
            ACME_UNFORMATTED="cmd/ak/main.go\n",
            ACME_BROKEN="go vet darwin/arm64 go build windows/amd64")
        self.assertEqual((code, parts),
                         (1, ["fmt", "vet darwin/arm64", "build windows/amd64"]), out)
        self.assertIn("cmd/ak/main.go", out)
        self.assertEqual(calls, [TOOLCHAIN, "gofmt -l", "go vet linux/arm64", "go vet linux/amd64",
                                 "go vet darwin/arm64", "go vet windows/amd64",
                                 "go test -json -timeout 0 ./...", "go build linux/amd64",
                                 "go build linux/arm64", "go build darwin/arm64",
                                 "go build windows/amd64"])

    def test_a_failing_vet_of_the_callers_own_platform_is_named_by_it_and_given_runs_there(self):
        code, out, parts, _ = self.checked(ACME_BROKEN="go vet linux/arm64")
        self.assertEqual((code, parts), (1, ["vet linux/arm64"]), out)
        self.assertIn("go vet linux/arm64 broke", out)
        code, out, parts, calls = self.checked("vet linux/arm64", host="linux/amd64",
                                               ACME_BROKEN="go vet linux/arm64")
        self.assertEqual((code, parts, calls), (1, ["vet linux/arm64"],
                                                [TOOLCHAIN, "go vet linux/arm64"]), out)

    def test_a_json_vet_fails_by_what_it_finds_and_a_build_by_its_exit_code_alone(self):
        code, out, parts, _ = self.checked("vet linux/arm64", ACME_PRINTS=CLEAN)
        self.assertEqual((code, parts), (0, []), out)
        code, out, parts, _ = self.checked("vet linux/arm64", ACME_PRINTS=CLEAN + FOUND)
        self.assertEqual((code, parts), (1, ["vet linux/arm64"]), out)
        self.assertIn("wrong type", out)
        code, out, parts, _ = self.checked("build linux/arm64", ACME_PRINTS=BUILT)
        self.assertEqual((code, parts), (0, []), out)

    def test_the_callers_own_platform_go_ships_on_is_vetted_first_and_once(self):
        _, out, _, calls = self.checked(host="darwin/arm64")
        self.assertEqual([call for call in calls if call.startswith("go vet")],
                         ["go vet darwin/arm64", "go vet linux/amd64", "go vet linux/arm64",
                          "go vet windows/amd64"], out)

    def test_given_parts_it_runs_just_those_after_the_toolchain_check(self):
        code, out, parts, calls = self.checked(f"{ACME}.TestFixApi", WIDGET, "build windows/amd64")
        self.assertEqual((code, parts), (0, []), out)
        self.assertEqual(json.loads((self.root / "times").read_text()).keys(),
                         {f"{ACME}.TestFixApi", WIDGET, "build windows/amd64"})
        self.assertEqual(calls, [TOOLCHAIN,
                                 f"go test -json -timeout 0 -run ^TestFixApi$ {ACME}",
                                 f"go test -json -timeout 0 {WIDGET}", "go build windows/amd64"])

    def test_a_given_test_that_runs_nowhere_fails_saying_it_is_not_there_naming_no_part(self):
        code, out, parts, _ = self.checked(f"{ACME}.TestGone")
        self.assertEqual((code, parts, json.loads((self.root / "times").read_text())),
                         (1, [], {}), out)
        self.assertIn(f"{ACME}.TestGone is not there", out)

    def test_the_callers_goflags_hold_in_every_run(self):
        for parts in ((), (f"{ACME}.TestFixApi", "vet linux/arm64")):
            calls = self.checked(*parts)[3]
            self.assertEqual(self.read("flags"), [GOFLAGS] * len(calls))


if __name__ == "__main__":
    unittest.main()
