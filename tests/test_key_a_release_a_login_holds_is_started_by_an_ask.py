"""A release a login holds is started by an ask, never by the tick that finds the login lasting.

The tick's hourly ask that finds a release a second time in a row starts its upgrade, unless a
login its gates would not outlast holds it.  The installer takes what the channel holds when it
starts, so a tick inside the hour that finds the login lasting starts nothing, whatever the
channel holds by then; the next hourly ask starts the release where it still finds it, and only
records a newer one.  Black-box, on the fixtures of
tests/test_key_update_waits_for_lasting_logins.py: HOME/agentkit is the program `AK_BIN` names,
each tick runs that copy, and the Home's only harness and login are Claude's; claude and npm are
fakes keeping the installed release and the channel's in files, and an hour goes by as the record
of each ask is set back.  This test fails against `/bin/false`.
"""

import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import BOXED, LOG, Home, rerun_boxed
from fixtures.akinstall import Install

HOUR = 60 * 60


def starts(release):
    return f"claude 2.1.0 is behind {release}: upgrading it in the background"


@unittest.skipUnless(BOXED, "no bwrap able to box the test here")
class StartedByAnAsk(unittest.TestCase):
    def setUp(self):
        """claude 2.2.0 found by two asks an hour apart, the second held by a login lapsing in ten
        minutes, which is then renewed to last eight hours."""
        self.home = home = Home()
        self.addCleanup(home.close)
        home.fake("security", "#!/bin/sh\nexit 1\n")    # no Keychain: the login is the file
        akconfig.write(home, ["opus"])
        install = Install(home)
        self.ak = install.ak
        # Claude's adapter alone, so a lend asks Claude's login alone: Go lends no Muse or
        # OpenCode login yet.  It runs the shipped one, which finds its checkout by its own path.
        adapter = home.root / "adapters" / "claude.sh"
        adapter.parent.mkdir()
        shipped = shlex.quote(str(install.at / "adapters" / "claude.sh"))
        adapter.write_text(f'#!/bin/sh\nexec {shipped} "$@"\n')
        adapter.chmod(0o755)
        self.env = {"AGENTKIT_ADAPTER_DIR": str(adapter.parent)}
        root = shlex.quote(str(home.root))
        home.fake("claude", f'#!/bin/sh\n[ "$1" != --version ] || exec cat {root}/claude\nexit 1\n')
        home.fake("npm", LOG.format(python=shlex.quote(sys.executable),
                                    log=shlex.quote(str(home.log("npm"))))
                  + f'[ "$*" != "view @anthropic-ai/claude-code version" ] || '
                    f'exec cat {root}/channel\nexit 1\n')
        (home.root / "claude").write_text("2.1.0 (Claude Code)\n")
        self.channel("2.2.0")
        soon = self.login(10 * 60)
        self.assertEqual(self.tick(), [])
        self.passes(HOUR)
        lapses = time.strftime("%Y-%m-%d %H:%M", time.gmtime(soon))
        self.assertEqual(self.tick(), [
            f"claude's upgrade waits: claude's login lapses at {lapses}, before it could end"])
        self.login(8 * 60 * 60)

    def channel(self, release):
        (self.home.root / "channel").write_text(f"{release}\n")

    def login(self, lasts):
        """Claude's login, lapsing `lasts` seconds from now with no refresh token; when."""
        ends = int(time.time() + lasts)
        self.home.write(".claude/.credentials.json", {"claudeAiOauth": {
            "accessToken": "acme-seat", "expiresAt": ends * 1000, "subscriptionType": "max"}})
        return ends

    def asks(self):
        """How often claude's latest release was asked."""
        return len(self.home.calls("npm"))

    def passes(self, seconds):
        """`seconds` go by for the record of each harness's last ask and start."""
        path = self.home.path / ".agentkit" / "state" / "harness-latest.json"
        path.write_text(json.dumps({name: {key: value - seconds if isinstance(value, (int, float))
                                           else value for key, value in entry.items()}
                                    for name, entry in json.loads(path.read_text()).items()}))

    def tick(self):
        """One `ak watch` of the live copy: what it said of claude's upgrade."""
        done = self.home.run(self.ak, "watch", env=self.env)
        self.assertEqual(done.code, 0, done.out + done.err)
        return [line for line in done.out.splitlines() if line.startswith("claude")]

    def test_the_next_hourly_ask_starts_the_release_it_still_finds(self):
        self.assertEqual(self.tick(), [])       # the login lasts, but the hour is not up
        self.assertEqual(self.asks(), 2)
        self.passes(HOUR)
        self.assertEqual(self.tick(), [starts("2.2.0")])
        self.assertEqual(self.asks(), 3)

    def test_a_channel_moved_during_the_hold_is_only_recorded(self):
        self.channel("2.3.0")
        self.assertEqual(self.tick(), [])
        self.passes(HOUR)
        self.assertEqual(self.tick(), [])       # the ask finds 2.3.0 a first time
        self.assertEqual(self.asks(), 3)
        self.passes(HOUR)
        self.assertEqual(self.tick(), [starts("2.3.0")])


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
