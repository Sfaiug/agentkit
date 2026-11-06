"""Every box writes the account's Go build cache, wherever `go env -w` saved it, so what one turn,
check or proof compiled serves the next (tests/test_key_a_turn_builds_go.py); a check boxed
inside a turn still writes its HOME for nothing, and a credential kept in the cache stays hidden."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
from fixtures.sandbox import account_home  # noqa: E402
from agentkit import box  # noqa: E402

# The turn's command: a check it boxes writes HOME, then moves HOME, as a proof may, and writes
# Go's cache.
TURN = r'''import os, subprocess, sys
from agentkit import box
out, work = sys.argv[1:]
os.mkdir(out)
check = 'echo check > "$HOME/check-write" && HOME=/var/tmp && echo built > "$GOCACHE/entry"'
with box.command(["sh", "-c", check], dict(os.environ), out, cwd=work,
                 home_overlay=True) as (cmd, env, spawn):
    sys.exit(subprocess.run(cmd, env=env, cwd=work, timeout=60,
                            pass_fds=spawn["pass_fds"]).returncode)
'''


class GoCache(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-box-go-cache-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home, self.work, self.out = (Path(tmp.name, name) for name in ("home", "work", "out"))
        for path in (self.home, self.work, self.out):
            path.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ("GOCACHE", "GOENV", "XDG_CACHE_HOME", "XDG_CONFIG_HOME")}
        self.env.update(HOME=str(self.home), GOTOOLCHAIN="local", PYTHONPATH=str(REPO))
        # under HOME, where a mount of it would leave the check's HOME read-only
        self.cache = self.home / "acme-go-build"
        subprocess.run(["go", "env", "-w", f"GOCACHE={self.cache}"], env=self.env, cwd=tmp.name,
                       check=True)

    def boxed(self, argv, out):
        with account_home(self.home), box.command(argv, self.env, out, cwd=self.work) as (
                cmd, env, spawn):
            return subprocess.run(cmd, env=env, cwd=self.work, capture_output=True, text=True,
                                  timeout=120, pass_fds=spawn.get("pass_fds", ()))

    def test_what_a_box_compiles_stays_for_the_next(self):
        result = self.boxed([sys.executable, "-B", "-c", TURN, str(self.out / "check"),
                             str(self.work)], self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.cache / "entry").read_text(), "built\n")
        self.assertFalse((self.home / "check-write").exists())
        # a box without an out dir, so without a scratch to mount the cache in
        result = self.boxed(["sh", "-c", 'echo built > "$GOCACHE/plain"'], None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.cache / "plain").read_text(), "built\n")

    def test_a_credential_kept_in_the_cache_stays_hidden(self):
        store = self.cache / "credentials"
        self.cache.mkdir()
        store.write_text("fixture-credential\n")
        (self.home / ".gitconfig").write_text(f"[credential]\n\thelper = store --file {store}\n")
        read = 'store="$(go env GOCACHE)/credentials"; cat "$store"; echo overwritten > "$store"'
        for out in (self.out, None):
            with self.subTest(out=out):
                self.assertNotIn("fixture-credential", self.boxed(["sh", "-c", read], out).stdout)
                self.assertEqual(store.read_text(), "fixture-credential\n")


if __name__ == "__main__":
    unittest.main()
