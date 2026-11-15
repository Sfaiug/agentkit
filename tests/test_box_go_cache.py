"""A check's box keeps Go's build cache in its home, and names the account's to a command that
moves HOME; a turn's box shows the account's beneath writes of its own, kept in its run until
the box ends (tests/test_key_a_turn_builds_on_the_accounts_go_cache.py)."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
from fixtures.sandbox import account_home  # noqa: E402
from agentkit import box  # noqa: E402

# What the account's cache holds, before a check's command runs.
HELD = "account\n"


class GoCache(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-box-go-cache-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / "out").mkdir()
        (self.home / "workspace").mkdir()

    def checked(self, argv, env=None, **kwargs):
        """argv run in a check's box, HOME and the account's home this test's."""
        return self.turned(argv, env, home_overlay=True, **kwargs)

    def turned(self, argv, env=None, **kwargs):
        """argv run in a turn's box, HOME and the account's home this test's."""
        home = self.home
        env = {**{key: value for key, value in os.environ.items()
                  if key not in ("GOCACHE", "XDG_CACHE_HOME")},
               "HOME": str(home), "GOTOOLCHAIN": "local", **(env or {})}
        with patch.dict(os.environ, {"HOME": str(home)}), account_home(home), box.command(
                argv, env, home / "out", cwd=home / "workspace", **kwargs) as (cmd, env, spawn):
            return subprocess.run(cmd, env=env, cwd=home / "workspace", capture_output=True,
                                  text=True, timeout=120, pass_fds=spawn["pass_fds"])

    def test_a_check_keeps_the_homes_cache(self):
        result = self.checked(["go", "env", "GOCACHE"])
        self.assertEqual((result.returncode, result.stdout.strip()),
                         (0, str(self.home / ".cache/go-build")), result.stderr)

    def test_a_moved_home_reads_the_accounts_cache(self):
        cache = self.home / ".cache/go-build"
        cache.mkdir(parents=True)
        (cache / "held").write_text(HELD)
        result = self.checked(["sh", "-c", 'export HOME="$(mktemp -d)" && cat "$GOCACHE/held" '
                                           '&& echo check > "$GOCACHE/own"'])
        self.assertEqual((result.returncode, result.stdout), (0, HELD), result.stderr)
        self.assertEqual(sorted(path.name for path in cache.iterdir()), ["held"])

    def test_a_cache_named_with_any_bytes_is_named_as_it_is(self):
        # A name may end in a space and hold bytes no text encoding reads.
        cache = Path(os.fsdecode(os.fsencode(self.home / "go-build") + b"\xff "))
        cache.mkdir()
        (cache / "held").write_text(HELD)
        goenv = self.home / "go-env"
        goenv.write_bytes(b"GOCACHE=" + os.fsencode(cache) + b"\n")
        result = self.checked(["sh", "-c", 'export HOME="$(mktemp -d)" && cat "$GOCACHE/held"'],
                              {"GOENV": str(goenv)})
        self.assertEqual((result.returncode, result.stdout), (0, HELD), result.stderr)

    def test_a_cache_holding_a_writable_place_is_not_named(self):
        # What a command wrote through GOCACHE there would stay in the account's cache.
        place = self.home / ".cache/go-build/ab"
        place.mkdir(parents=True)
        result = self.checked(["sh", "-c", 'test -z "${GOCACHE+named}"'], places=(str(place),))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_hidden_cache_is_not_named(self):
        hidden = self.home / "hidden"
        (hidden / "go-build").mkdir(parents=True)
        (hidden / "go-build" / "held").write_text(HELD)
        result = self.checked(
            ["sh", "-c", 'test -z "${GOCACHE+named}" && ls -A "$0"', str(hidden)],
            {"XDG_CACHE_HOME": str(hidden)}, hidden=(hidden,))
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_a_turn_reads_the_accounts_cache_and_writes_in_its_run(self):
        cache = self.home / ".cache/go-build"
        cache.mkdir(parents=True)
        (cache / "held").write_text(HELD)
        out = self.home / "out"
        result = self.turned(["sh", "-c", 'cat "$GOCACHE/held" && echo turn > "$GOCACHE/own" '
                                          '&& find "$0" ! -readable -prune -o -name own -print',
                             str(out)])
        self.assertEqual(result.returncode, 0, result.stderr)
        held, own = result.stdout.splitlines()
        # On disk in the turn's run, never in memory, and gone with the box.
        self.assertEqual((held + "\n", Path(own).is_relative_to(out)), (HELD, True))
        self.assertEqual((sorted(path.name for path in cache.iterdir()),
                          list(self.home.rglob("own"))), (["held"], []))

    def test_a_turn_is_not_shown_a_cache_holding_a_hidden_place(self):
        # The overlay shows the cache as the host holds it, past the masks.
        cache = self.home / ".cache/go-build"
        cache.mkdir(parents=True)
        (cache / "held").write_text(HELD)
        result = self.turned(["sh", "-c", 'test ! -e "$GOCACHE/held"'], hidden=(cache / "held",))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_turn_whose_run_takes_no_overlay_has_a_cache_of_its_own(self):
        # The kernel keeps no overlay's writes on another overlay, as the out dir is here.
        cache = self.home / ".cache/go-build"
        cache.mkdir(parents=True)
        (cache / "held").write_text(HELD)
        out = str(self.home / "out")
        turn = (f"import os, subprocess, sys; sys.path[:0] = [{str(REPO)!r}]\n"
                "from agentkit import box\n"
                "with box.command(sys.argv[1:], os.environ, os.environ['OUT']) as (cmd, env, s):\n"
                "    sys.exit(subprocess.run(cmd, env=env, pass_fds=s['pass_fds']).returncode)\n")
        env = {**{key: value for key, value in os.environ.items()
                  if key not in ("GOCACHE", "XDG_CACHE_HOME")},
               "HOME": str(self.home), "GOTOOLCHAIN": "local", "OUT": out}
        result = subprocess.run(
            ["bwrap", "--unshare-user", "--dev-bind", "/", "/", "--overlay-src", out,
             "--tmp-overlay", out, "--", sys.executable, "-I", "-c", turn, "sh", "-c",
             'test ! -e "$GOCACHE/held" && mkdir "$GOCACHE" && echo turn > "$GOCACHE/own"'],
            env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
