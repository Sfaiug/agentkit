"""A usage read made with an older config never takes a subscription's reading away.

On 27 Oct the owner added a second subscription on `c` while a menu's probe still held the
config from before: every few minutes it read the provider as one login and wrote that one
record over both accounts' readings, and both meters flipped to `— no reading yet`.
`usage.json` follows the config as it is on disk at each write: the usual login's reading goes
under `default` where the accounts list it, and never over the accounts' records.

Black-box: the program `AK_BIN` names, its menus in a person's terminals
(tests/fixtures/akterm.py) over a temporary HOME, its harnesses the fakes of
tests/fixtures/fakeadapter.py, Codex's asked at every probe (`probe_every = 1`) and answering
a week 30% used.  A menu on its main screen, opened with ChatGPT one login, probes once a
minute; `ak usage`, reading with the config on disk, stands in for the tick.  Judged by
usage.json and the terminal; this test fails against `/bin/false`.
"""

import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
PAGE, ADD = "agentkit · config · subscriptions", "agentkit · config · add a subscription"
PROBE = 70          # the menu probes once a minute; a bound past its next one
METER = re.compile(r"ChatGPT II\s+[▰▱]+  70% left")


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def title(screen):
    return lines(screen)[0].rsplit(" ", 1)[0].strip()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class UsageFollowsConfigOnDisk(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        codex = self.fakes["codex"]
        codex.manifest.write_text(codex.manifest.read_text().replace(
            "[usage]\n", "[usage]\nprobe_every = 1\n", 1))
        codex.answer("usage", json.dumps({"meters": [
            {"name": "weekly", "used": 30, "window_secs": 604800,
             "resets_at": time.time() + 3 * 86400}]}))
        self.models = {"fable": "claude", "astra": "codex"}
        akconfig.write(self.home, self.models)
        self.usage = self.home.path / ".agentkit/state/usage.json"
        self.open()
        self.opened = self.landed(0)          # its first probe, with ChatGPT one login

    def open(self):
        """A menu in a person's terminal, on its main screen."""
        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane,
                        "sleep 86400", server=SERVER)
        term.wait(lambda screen: MAIN_KEYS in lines(screen))
        return term

    def snapshot(self):
        try:
            return json.loads(self.usage.read_text())
        except (OSError, ValueError):
            return {}

    def landed(self, since, bound=PROBE):
        """The menu's `fetched_at` once a probe of its started after `since` has written."""
        deadline = time.monotonic() + bound
        while (self.snapshot().get("fetched_at") or 0) <= since:
            self.assertLess(time.monotonic(), deadline, "the menu never probed again")
            time.sleep(0.2)
        return self.snapshot()["fetched_at"]

    def read_as_on_disk(self):
        done = self.home.ak("usage")
        self.assertEqual(done.code, 0, done.err)

    def test_a_second_account_s_reading_outlives_a_probe_holding_the_older_config(self):
        akconfig.write(self.home, self.models,
                       providers={"openai": {"mode": "subscription",
                                             "accounts": ["default", "two"]}})
        self.read_as_on_disk()
        two = self.snapshot()["providers"]["openai"]["accounts"]["two"]
        self.assertTrue(two.get("meters"), two)
        self.landed(self.opened)
        openai = self.snapshot()["providers"]["openai"]
        self.assertEqual(sorted(openai.get("accounts") or {}), ["default", "two"], openai)
        self.assertEqual(openai["accounts"]["two"]["probed_at"], two["probed_at"])
        self.assertTrue(openai["accounts"]["default"].get("meters"), openai)

    def test_a_subscription_added_on_c_keeps_its_meter_across_the_menu_s_probes(self):
        owner = self.open()                           # `c` never probes; the menu open before does
        owner.keys("c")
        owner.wait("› Fable 5.1")
        owner.keys("Down", "Down", "Down")            # past GPT-6-Astra and `Models`
        owner.wait("› Subscriptions")
        owner.keys("Enter")
        owner.wait(lambda screen: title(screen) == PAGE)
        for _ in range(4):                            # past Claude and ChatGPT
            if "› + add a subscription" in owner.screen():
                break
            owner.keys("Down")
            time.sleep(0.3)
        owner.wait("› + add a subscription")
        owner.keys("Enter")
        offered = owner.wait(lambda screen: title(screen) == ADD and "ChatGPT II" in screen)
        rows = [line[2:] for line in lines(offered)[2:] if line[2:]]
        owner.keys(*["Down"] * rows.index("ChatGPT II"), "Enter")
        owner.wait(lambda screen: title(screen) == PAGE and "› ChatGPT II" in screen)
        self.read_as_on_disk()
        owner.wait(lambda screen: METER.search(screen))
        since, seen, deadline = self.snapshot()["fetched_at"], None, time.monotonic() + PROBE
        while seen is None or time.monotonic() < seen + 3:    # and the draw after it
            screen = owner.screen()
            self.assertRegex(screen, METER)
            if seen is None:
                self.assertLess(time.monotonic(), deadline, "the menu never probed")
                if (self.snapshot().get("fetched_at") or 0) > since:
                    seen = time.monotonic()
            time.sleep(0.05)
        self.assertEqual(title(screen), PAGE)


if __name__ == "__main__":
    unittest.main()
