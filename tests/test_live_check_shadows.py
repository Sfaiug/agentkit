"""A live check of a commit shadows Go on its home before its suite: tests/live.sh runs
tests/shadow.py's previews there, writes what each found to the check's shadow.json, keeps each
difference one confirms as a case under the Home's .agentkit/tmp/shadow/cases, and exits as its
suite does; run as a harness gate, or with `AK_LIVE_FAILED` naming anything but
`<check>/failed`, it shadows nothing.  An agreeing Go adds today to the streak beside the cases, a
Go one line apart restarts it, empty, and a Go that does not build leaves it as it was, as the
streak command, `tests/shadow.py --streak <it> --holds N`, tells.

On an akinstall Home, each case commits this checkout's tests/live.sh and tests/shadow.py, with
what they import, beside a stand-in tests/smoke.sh exiting as the case picks, and runs the check
as LIVE_RUN in agentkit/update.py does: at `<check>/tree`, with `AK_LIVE_FAILED` at
`<check>/failed`.  A stand-in `go` builds the case's fake Go, the commit's Python ak with one line
more or none.  The check runs boxed as tests/test_shadow.py boxes the shadow, so /var/tmp can
hold the shadow's overlays.
"""

import json
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, REPO, Home, boxable
from fixtures.akinstall import Install
from shadow import PREVIEWS
from test_shadow import OUTER

# What the check needs of the commit's tests/ but its suite: the shadow, and what it imports.
CARRIED = ("live.sh", "shadow.py", "fixtures/akbin.py", "test_go.py", "suite_shares.py")
# The stand-in `go`: `go build -o <path> ...` writes there a fake Go running the commit's bin/ak,
# two folders up from its go/bin/ak, writing no bytecode, as no Go does, then `{more}`, and
# exiting as Python did.
BUILD = """for arg do [ "$was" != -o ] || out=$arg; was=$arg; done
mkdir -p "$(dirname "$out")"
cat >"$out" <<'EOF'
#!/bin/sh
PYTHONDONTWRITEBYTECODE=1 "$(dirname "$0")/../../bin/ak" "$@"
code=$?
{more}
exit $code
EOF
chmod +x "$out"
"""
LINE = "a line only go prints"
CASES = Path(".agentkit/tmp/shadow/cases")
STREAK = Path(".agentkit/tmp/shadow/streak")


def day(back):
    """The UTC day `back` days before today, as the streak holds it."""
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - back * 86400))


@unittest.skipUnless(boxable(), "no bwrap able to build a box here")
class ALiveCheckRunsTheShadow(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.seed = Install(self.home).seed

    def live(self, suite, more, failed="failed"):
        """Run the live check of a commit whose suite exits `suite`, its Go built with `more`
        (None: no Go builds), and `AK_LIVE_FAILED` at `failed` within the check's folder: what it
        did, and the check's folder."""
        for name in CARRIED:
            copy = self.seed / "tests" / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes((REPO / "tests" / name).read_bytes())
        (self.seed / "tests" / "smoke.sh").write_text(f"echo suite\nexit {suite}\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "the shadow and a stand-in suite")
        commit = self.git("rev-parse", "HEAD")
        check = self.home.path / ".agentkit/state/live-checks" / f"{commit}-{int(time.time())}"
        self.git("worktree", "add", "--quiet", "--detach", str(check / "tree"), commit)
        logged = LOG.format(python=shlex.quote(sys.executable),
                            log=shlex.quote(str(self.home.log("go"))))
        self.home.fake("go", logged + ("exit 1\n" if more is None else BUILD.format(more=more)))
        # As the tick starts it, nothing in its environment keeps Python's bytecode out of the
        # check's tree under HOME.
        done = self.home.run(*self.home.box(OUTER), "bash", "tests/live.sh", cwd=check / "tree",
                             env={"AK_LIVE_FAILED": str(check / failed),
                                  "PYTHONDONTWRITEBYTECODE": None, "PYTHONPYCACHEPREFIX": None},
                             timeout=900)
        return done, check

    def cases(self):
        """What each case the Home keeps is of: the command, the kind and the words."""
        return sorted((kept["ak"], kept["kind"], kept["what"])
                      for kept in (json.loads((case / "case.json").read_text())
                                   for case in (self.home.path / CASES).glob("*")))

    def holds(self, n):
        """The streak command's exit for `n` days, and the days it printed."""
        done = self.home.run(sys.executable, REPO / "tests" / "shadow.py",
                             "--streak", self.home.path / STREAK, "--holds", str(n))
        return done.code, done.out.splitlines()

    def git(self, *args):
        done = self.home.run("git", "-C", str(self.seed), *args)
        self.assertEqual(done.code, 0, done.err)
        return done.out.strip()

    def test_an_agreeing_go(self):
        done, check = self.live(1, "")
        said = done.out + done.err
        self.assertEqual(done.code, 1, said)
        record = json.loads((check / "shadow.json").read_text())
        self.assertEqual([(preview["ak"], preview["ran"], preview["differences"])
                          for preview in record["previews"]],
                         [(list(argv), True, []) for argv in PREVIEWS], said)
        # a line for each preview, in the list's order, then the suite's
        lines = done.out.splitlines()
        self.assertEqual([line.partition(": ran, ")[0] for line in lines],
                         [f"shadow: ak {shlex.join(argv)}" for argv in PREVIEWS] + ["suite"], said)
        self.assertEqual(self.cases(), [], said)
        self.assertEqual(self.holds(1), (0, [day(0)]), said)

    def test_six_days_in_a_row_and_an_agreeing_go(self):
        planted = [day(back) for back in range(6, 0, -1)]
        self.home.write(STREAK, planted)
        # yesterday the last: today's check may be yet to run
        self.assertEqual((self.holds(6)[0], self.holds(7)[0]), (0, 1))
        done, _ = self.live(0, "")
        said = done.out + done.err
        self.assertEqual(done.code, 0, said)
        self.assertEqual(self.holds(7), (0, [*planted, day(0)]), said)
        self.assertEqual(self.holds(8)[0], 1, said)

    def test_a_go_that_prints_one_line_more(self):
        self.home.write(STREAK, [day(0)])
        done, check = self.live(0, f'echo "{LINE}"')
        said = done.out + done.err
        self.assertEqual(done.code, 0, said)
        for preview in json.loads((check / "shadow.json").read_text())["previews"]:
            with self.subTest(preview["ak"]):
                self.assertTrue(preview["ran"], said)
                self.assertIn(["line", f"only go: stdout: {LINE}"], preview["differences"], said)
        self.assertEqual(self.cases(), sorted((list(argv), "line", f"only go: stdout: {LINE}")
                                              for argv in PREVIEWS), said)
        self.assertEqual(self.holds(1), (1, []), said)

    def test_a_go_that_does_not_build(self):
        planted = [day(0)]
        self.home.write(STREAK, planted)
        done, check = self.live(0, None)
        said = done.out + done.err
        self.assertEqual(done.code, 0, said)
        record = json.loads((check / "shadow.json").read_text())
        self.assertEqual(record["nothing_ran"], "no Go was built")
        self.assertEqual([preview["ran"] for preview in record["previews"]],
                         [False] * len(PREVIEWS))
        self.assertEqual(self.holds(1), (0, planted), said)

    def test_a_harness_gate(self):
        log = self.home.path / ".agentkit" / "update.log"
        done, _ = self.live(1, "", failed=f"{log}.failed")
        said = done.out + done.err
        self.assertEqual(done.code, 1, said)
        self.assertEqual(self.home.calls("go"), [])
        self.assertEqual(list(self.home.path.rglob("shadow.json")), [])

    def test_the_check_folder_itself(self):
        done, _ = self.live(1, "", failed=".")
        said = done.out + done.err
        self.assertEqual(done.code, 1, said)
        self.assertEqual(self.home.calls("go"), [])
        self.assertEqual(list(self.home.path.rglob("shadow.json")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
