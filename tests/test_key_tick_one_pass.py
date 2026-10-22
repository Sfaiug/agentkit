"""`ak watch` runs one whole tick, keeps its state in watch.json and holds the one-tick lock.

Cron starts a tick every few minutes whatever the last one is doing, so a tick holds a lock on
state/watch.tick.lock for its whole run, and a tick that finds it held runs nothing and says
whose it is, and that it may be hung once it has held it half an hour.  What the ticks remember
between them is the JSON object state/watch.json, with the boot it was written in, which the
menu and the next tick read.  Anything but `--dry-run` after `ak watch` is a usage error that
runs nothing: models learn the command by typing at it.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, its GitHub tests/fixtures/fakegh.py; this
test fails against `/bin/false`.
"""

import fcntl
import json
import socket
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures import akconfig

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
KEPT = ("reviewed", "own", "stalls", "seen_at", "after_merge")
BOOT = Path("/proc/sys/kernel/random/boot_id")
USAGE = "ak watch: usage: ak watch [--dry-run]  (got {!r})\n"


def offline(home):
    """The tick asks the public model boards over HTTP itself, not through a tool on PATH: every
    proxy an HTTP client honours names a loopback port nobody listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"))


class OneTick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        offline(home)
        akconfig.write(home, ["opus"])
        GitHub(home)
        cls.state = home.path / ".agentkit" / "state"
        cls.tick = home.ak("watch")

    def test_a_tick_succeeds_and_keeps_its_state_in_watch_json(self):
        self.assertEqual(self.tick.code, 0, self.tick.err)
        kept = json.loads((self.state / "watch.json").read_text())
        self.assertEqual({key: type(kept.get(key)) for key in KEPT}, dict.fromkeys(KEPT, dict))
        self.assertEqual(kept["boot_id"], BOOT.read_text().strip() if BOOT.exists() else None)

    def test_a_tick_asks_github_who_the_owner_is(self):
        self.assertIn(["api", "user"], self.home.calls("gh"))

    def test_a_tick_with_no_seat_and_no_run_touches_none_of_the_owners_units(self):
        self.assertEqual(self.tick.code, 0, self.tick.err)
        for tool in ("systemctl", "systemd-run", "loginctl"):
            with self.subTest(tool):
                self.assertEqual(self.home.calls(tool), [])

    def test_a_tick_finding_the_lock_held_runs_nothing_and_says_whose_it_is(self):
        kept = (self.state / "watch.json").read_bytes()
        asked = len(self.home.calls("gh"))
        held = {2400: "tick already running (pid 4242, for 40 min)\nWARN the tick holding the "
                      "lock has been running for 40 min; look at it, and kill it if it is hung\n",
                0: "tick already running (pid 4242, for 0 min)\n"}
        for ago, said in held.items():
            with self.subTest(ago=ago):
                lock = self.home.write(".agentkit/state/watch.tick.lock", "4242\n", ago=ago)
                with lock.open("r") as holder:
                    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    done = self.home.ak("watch")
                self.assertEqual((done.code, done.out, done.err), (0, said, ""))
                self.assertEqual((self.state / "watch.json").read_bytes(), kept)
                self.assertEqual(len(self.home.calls("gh")), asked)

    def test_anything_but_dry_run_is_a_usage_error_that_runs_nothing(self):
        with Home() as home:
            for args in (["x"], ["--bogus"], ["x", "--dry-run"], ["--dry-run", "x"]):
                with self.subTest(args=args):
                    done = home.ak("watch", *args)
                    self.assertEqual((done.code, done.out, done.err),
                                     (2, "", USAGE.format(args[0])))
            self.assertEqual(list((home.path / ".agentkit" / "state").iterdir()), [])
            self.assertEqual(home.calls("gh"), [])
            self.assertNotEqual(home.tmux("list-sessions").code, 0)


if __name__ == "__main__":
    unittest.main()
