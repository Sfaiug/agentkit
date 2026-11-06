"""A check's box keeps Go's build cache in its home, and names the account's to a command that
moves HOME, where a turn's box has one of its own (tests/test_key_a_turn_builds_go.py)."""

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
        home = self.home
        env = {**{key: value for key, value in os.environ.items()
                  if key not in ("GOCACHE", "XDG_CACHE_HOME")},
               "HOME": str(home), "GOTOOLCHAIN": "local", **(env or {})}
        with patch.dict(os.environ, {"HOME": str(home)}), account_home(home), box.command(
                argv, env, home / "out", cwd=home / "workspace", home_overlay=True,
                **kwargs) as (cmd, env, spawn):
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


if __name__ == "__main__":
    unittest.main()
