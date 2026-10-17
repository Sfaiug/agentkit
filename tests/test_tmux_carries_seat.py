"""Whatever a seat starts in tmux speaks for that seat: the seat's tmux shim gives every command
that starts a process `-e AGENTKIT_SESSION=<seat>`, so an `ak run --review-pr` started in a tmux
session the seat made is the seat's own, as it is from the seat's shell.

Offline: the shim is `tmux` first on PATH and a fake real tmux behind it records the argv it is
handed, NUL-separated, so a word holding spaces or a newline is seen whole.  No tmux server is
asked or touched; that tmux keeps the last of two `-e` for one name is its own (tmux 3.5a).
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "tools/tmux-shim"
REAL = "#!/bin/sh\nprintf '%s\\0' \"$@\" > \"$RAN_LOG\"\n"
SEAT = ["-e", "AGENTKIT_SESSION=mine"]
OWNED = [*SEAT, "-e", "AK_TMUX_OWNER=mine"]      # a new session also names its creator
REVIEW = "ak run --review-pr https://github.com/acme/api/pull/7 --bg"


class TmuxCarriesSeat(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        (home / ".agentkit/state").mkdir(parents=True)
        (home / ".agentkit/state/session-mine.json").write_text("{}\n")
        shimdir, realdir = home / "shim", home / "real"
        shimdir.mkdir()
        realdir.mkdir()
        (shimdir / "tmux").symlink_to(SHIM)
        (realdir / "tmux").write_text(REAL)
        (realdir / "tmux").chmod(0o755)
        self.ran = home / "ran.log"
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("AK_RUN_ROLE", "AGENTKIT_SESSION", "TMUX")}
        self.env.update(HOME=str(home), AGENTKIT_SESSION="mine", RAN_LOG=str(self.ran),
                        PATH=f"{shimdir}{os.pathsep}{realdir}{os.pathsep}{os.environ.get('PATH', '')}")
        self.tmux = shimdir / "tmux"

    def handed(self, args, **env):
        """The argv the real tmux got for that seat's call."""
        self.ran.unlink(missing_ok=True)
        result = subprocess.run([str(self.tmux), *args], capture_output=True, text=True,
                                timeout=30, env={**self.env, **env})
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.ran.read_bytes().decode().split("\0")[:-1]

    def test_each_command_that_starts_a_process_carries_the_seat(self):
        for args, want in (
                (["new-session", "-d", "-s", "watch", REVIEW],
                 ["new-session", *OWNED, "-d", "-s", "watch", REVIEW]),
                (["new", "-d", "printf 'a b\nc'"], ["new", *OWNED, "-d", "printf 'a b\nc'"]),
                (["neww", "-t", "watch"], ["neww", *SEAT, "-t", "watch"]),
                (["new-w", "-t", "watch"], ["new-w", *SEAT, "-t", "watch"]),
                (["splitw", "-d", REVIEW], ["splitw", *SEAT, "-d", REVIEW]),
                (["split-window", "-d"], ["split-window", *SEAT, "-d"]),
                (["respawnp", "-k", "-t", "watch"], ["respawnp", *SEAT, "-k", "-t", "watch"]),
                (["respawn-window", "-k"], ["respawn-window", *SEAT, "-k"]),
                (["-L", "other", "-f", "/dev/null", "new-session", "-d"],
                 ["-L", "other", "-f", "/dev/null", "new-session", *OWNED, "-d"]),
                (["new-session", "-d", "-s", "w", ";", "split-window", "-t", "w", REVIEW],
                 ["new-session", *OWNED, "-d", "-s", "w", ";", "split-window", *SEAT, "-t", "w",
                  REVIEW]),
                # a word ending in `;` ends its command, which tmux reads as a `;` of its own
                (["new-session", "-d", "sleep 1;", "neww;", "splitw"],
                 ["new-session", *OWNED, "-d", "sleep 1", ";", "neww", *SEAT, ";", "splitw",
                  *SEAT]),
                # the seat's own -e comes later, and tmux keeps the last
                (["new-session", "-d", "-e", "AGENTKIT_SESSION="],
                 ["new-session", *OWNED, "-d", "-e", "AGENTKIT_SESSION="])):
            with self.subTest(args=args):
                self.assertEqual(self.handed(args), want)

    def test_what_starts_nothing_is_handed_on_as_typed(self):
        for args in (["list-sessions"], ["has-session", "-t", "=watch"],
                     ["send-keys", "-t", "mine", "new-session", "Enter"],   # an argument, no command
                     ["display-message", "-p", "neww"],
                     ["send-keys", "-t", "mine", "x\\;", "neww"],   # an escaped `;` ends nothing
                     ["n", "-d"]):                          # ambiguous: tmux refuses it itself
            with self.subTest(args=args):
                self.assertEqual(self.handed(args), args)

    def test_a_guard_that_fails_adds_nothing(self):
        args = ["new-session", "-d", "-s", "watch"]
        (self.ran.parent / ".agentkit/state/session-mine.json").write_text("{broken\n")
        self.assertEqual(self.handed(args), args)      # the refusal check raised

    def test_a_worker_and_a_shell_with_no_seat_add_nothing(self):
        args = ["new-session", "-d", "-s", "watch", REVIEW]
        for env in ({"AK_RUN_ROLE": "worker"}, {"AGENTKIT_SESSION": ""}):
            with self.subTest(env=env):
                self.assertEqual(self.handed(args, **env), args)


if __name__ == "__main__":
    unittest.main()
