"""tests/shadow.py on an akbin Home: Python in Go's place finds nothing, and each of seven fake
Gos, Python's ak with one thing more, is named by the kind of that one thing; the Home keeps
every byte and modification time; and where no box can be built, nothing runs."""

from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REPO, Home, boxable

SHADOW = REPO / "tests" / "shadow.py"
COMMAND = ("usage",)    # one that writes under HOME: ak's folders and its probes' locks
# A /var/tmp of the test's own, on a tmpfs: where the host's is itself an overlay, as a
# container's is, no overlay can keep its upper layer there.
OUTER = ("bwrap", "--dev-bind", "/", "/", "--tmpfs", "/var/tmp")
# Each fake Go: Python's ak, then one thing more, exiting as Python did.
GO = shlex.quote(str(REPO / "bin" / "ak")) + ' "$@"\ncode=$?\n{}\nexit $code'
MORE = (
    ("line", 'echo "a line only go prints"'),
    ("hand-over", 'echo "seat revival" >"$AK_HANDOVER"'),
    ("home", 'echo "{}" >"$HOME/.agentkit/state/go-only.json"'),
    # an extended attribute alone, of a file Python leaves be: its mode, time and bytes stay
    ("home", shlex.quote(sys.executable) + " -c 'import os, sys; os.setxattr(sys.argv[1], "
             '"user.acme", b"go")\' "$HOME/.gitconfig"'),
    # ... and of HOME itself, whose mode the box's upper layer does not share unless made to
    ("home", shlex.quote(sys.executable) + " -c 'import os, sys; os.setxattr(sys.argv[1], "
             '"user.acme", b"go")\' "$HOME"'),
    ("page", 'echo "a page only go sent" >>"$AK_NOTIFY_SINK_LOG"'),
    ("call", "tmux send-keys -t acme Enter 2>/dev/null"),
)


def every_byte_and_time(home):
    return {str(path): (path.read_bytes() if path.is_file() else None, path.lstat().st_mtime_ns)
            for path in (home, *sorted(home.rglob("*")))}


class Shadowed(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        # In the checkout, as the suite's sandboxes are: each run's box has a /tmp of its own.
        self.fakes = Path(tempfile.mkdtemp(prefix=".ak-test-shadow-", dir=REPO))
        self.addCleanup(shutil.rmtree, self.fakes)

    def fake(self, name, script):
        path = self.fakes / name
        path.write_text(f"#!/bin/sh\n{script}\n")
        path.chmod(0o755)
        return str(path)

    def shadow(self, *args, box=OUTER, env=None):
        done = self.home.run(*(self.home.box(box) if box else ()), sys.executable, SHADOW, *args,
                             "--home", str(self.home.path), "--", *COMMAND, env=env, timeout=900)
        return done.code, {kind for kind in (*dict(MORE), "exit") for line in done.out.splitlines()
                           if line.startswith(f"{kind}: ")}, done.out + done.err

    @unittest.skipUnless(boxable(), "no bwrap able to build a box here")
    def test_each_way_go_differs_is_named_and_the_home_is_kept(self):
        before = every_byte_and_time(self.home.path)
        code, named, said = self.shadow("--go", "python")
        self.assertEqual((code, named), (0, set()), said)
        for number, (kind, more) in enumerate(MORE):
            with self.subTest(kind, number=number):
                code, named, said = self.shadow("--go", self.fake(str(number), GO.format(more)))
                self.assertEqual((code, named), (1, {kind}), said)
        self.assertEqual(every_byte_and_time(self.home.path), before)

    @unittest.skipUnless(boxable(), "no bwrap able to build a box here")
    def test_bytes_their_user_cannot_read_are_compared(self):
        cache = self.home.path / "cache"
        cache.write_text("before")
        cache.chmod(0)
        # Each Go copies the file up by setting its mode again; one also rewrites its bytes and
        # puts back its time.  Where no unshare will read them, the runs cannot be judged.
        again = 'import os; os.chmod(os.path.expanduser("~/cache"), 0)'
        rewrite = ('import os; path = os.path.expanduser("~/cache"); was = os.stat(path); '
                   'os.chmod(path, 0o600); open(path, "w").write("after!"); '
                   'os.utime(path, ns=(was.st_atime_ns, was.st_mtime_ns)); os.chmod(path, 0)')
        self.fake("unshare", "exit 1")
        refused = {"PATH": f"{self.fakes}:{self.home.env['PATH']}"}
        for name, script, env, outcome in (("again", again, None, (0, set())),
                                           ("rewrite", rewrite, None, (1, {"home"})),
                                           ("unread", again, refused, (2, set()))):
            with self.subTest(name):
                more = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
                code, found, said = self.shadow("--go", self.fake(name, GO.format(more)), env=env)
                self.assertEqual((code, found), outcome, said)

    def test_where_no_box_can_be_built_nothing_runs(self):
        ran = self.fakes / "ran"
        self.fake("bwrap", "exit 1")
        program = self.fake("ak", f"touch {shlex.quote(str(ran))}")
        code, _, said = self.shadow("--python", program, "--go", program, box=(),
                                    env={"PATH": f"{self.fakes}:{self.home.env['PATH']}"})
        self.assertEqual(code, 2, said)
        self.assertFalse(ran.exists(), "a program ran outside a box")


if __name__ == "__main__":
    unittest.main(verbosity=2)
