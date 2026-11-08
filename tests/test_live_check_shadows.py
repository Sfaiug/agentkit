"""A live check of a commit shadows Go on its home before its suite: tests/live.sh runs
tests/shadow.py's previews there, writes what each found to the check's shadow.json, and exits as
its suite does; run as a harness gate, it shadows nothing.

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
# two folders up from its go/bin/ak, then `{more}`, and exiting as Python did.
BUILD = """for arg do [ "$was" != -o ] || out=$arg; was=$arg; done
mkdir -p "$(dirname "$out")"
cat >"$out" <<'EOF'
#!/bin/sh
"$(dirname "$0")/../../bin/ak" "$@"
code=$?
{more}
exit $code
EOF
chmod +x "$out"
"""
LINE = "a line only go prints"


@unittest.skipUnless(boxable(), "no bwrap able to build a box here")
class ALiveCheckRunsTheShadow(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.seed = Install(self.home).seed

    def live(self, suite, more, failed=None):
        """Run the live check of a commit whose suite exits `suite`, its Go built with `more`
        (None: no Go builds), and `AK_LIVE_FAILED` at `failed` if named: what it did, and the
        check's folder."""
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
        done = self.home.run(*self.home.box(OUTER), "bash", "tests/live.sh", cwd=check / "tree",
                             env={"AK_LIVE_FAILED": str(failed or check / "failed")},
                             timeout=900)
        return done, check

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

    def test_a_go_that_prints_one_line_more(self):
        done, check = self.live(0, f'echo "{LINE}"')
        said = done.out + done.err
        self.assertEqual(done.code, 0, said)
        for preview in json.loads((check / "shadow.json").read_text())["previews"]:
            with self.subTest(preview["ak"]):
                self.assertTrue(preview["ran"], said)
                self.assertIn(["line", f"only go: stdout: {LINE}"], preview["differences"], said)

    def test_a_go_that_does_not_build(self):
        done, check = self.live(0, None)
        said = done.out + done.err
        self.assertEqual(done.code, 0, said)
        record = json.loads((check / "shadow.json").read_text())
        self.assertEqual(record["nothing_ran"], "no Go was built")
        self.assertEqual([preview["ran"] for preview in record["previews"]],
                         [False] * len(PREVIEWS))

    def test_a_harness_gate(self):
        log = self.home.path / ".agentkit" / "update.log"
        done, _ = self.live(1, "", failed=f"{log}.failed")
        said = done.out + done.err
        self.assertEqual(done.code, 1, said)
        self.assertEqual(self.home.calls("go"), [])
        self.assertEqual(list(self.home.path.rglob("shadow.json")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
