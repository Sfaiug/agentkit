"""A host that is a listed machine obeys its own table's cap on runs at once: a stand-in's
config.toml is the home's copy, whose top-level `max_runs` is the other machine's number.

Black-box: AK_BIN in a temporary HOME with invented machines and no AK_MAX_RUNS but where a test
sets one, the tick's record saying acme-self's last answer named this host. A run is admitted
under acme-self's `max_runs`, not the top line's, and under no limit where its table has none;
`this one`'s page on `c` shows and changes that table's number, the top line untouched. Once
acme-self's last answer names another host, the top line is this host's again.
"""

from pathlib import Path
import socket
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal


class AListedHostObeysItsOwnCap(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.env.pop("AK_MAX_RUNS")      # the suites' own, over the file under test
        fakeadapter.install(self.home, claude="pass")
        self.write("max_runs = 2\n")
        self.named(True)

    def write(self, own):
        akconfig.write(self.home, ["fable"], settings={"max_runs": 5},
                       extra=f"[machines.acme-self]\n{own}[machines.acme-other]\nmax_runs = 7\n")

    def named(self, here):
        """The tick's record: acme-self's last answer named this host, or another unless `here`;
        acme-other's another, each another named after this host so no host is it."""
        at, host = time.time(), socket.gethostname()
        said = {"at": at, "system": "Linux", "processor": "arm64", "cores": 4, "memory_mb": 8192,
                "free_mb": 4096, "load": 0.5, "disk_free_mb": 102400, "battery": 0, "power": 1}
        self.home.write(".agentkit/state/machines.json", {
            name: {"checks": [[at, True]], "said": {**said, "name": shown}}
            for name, shown in (("acme-self", host if here else f"{host}-elsewhere"),
                                ("acme-other", f"{host}-other"))})

    def admitted(self, env=None):
        done = self.home.ak("run", "status", env=env)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out.splitlines()[0]

    def test_a_run_is_admitted_under_its_own_table_s_cap(self):
        self.assertIn("at most 2 runs at once", self.admitted())
        self.assertIn("at most 4 runs at once", self.admitted({"AK_MAX_RUNS": "4"}))
        self.write("")
        self.assertNotIn("runs at once", self.admitted())
        # named as another host, acme-self is another machine, and the top line this host's
        self.named(False)
        self.assertIn("at most 5 runs at once", self.admitted())

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_this_one_s_page_shows_and_changes_its_own_table(self):
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40),
                             env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen
                       and "esc back" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "config · machines" in screen
                       and "› this one" in screen and "esc back" in screen)
        self.term.keys("Enter")
        shown = self.term.wait(lambda screen: "config · machines · this one" in screen
                               and "› runs at once" in screen and "esc back" in screen)
        self.assertIn("runs at once 2", " ".join(shown.split()))

        for typed, number, said in (("3", 3, "3"), ("0", None, "no limit")):
            self.term.keys("Enter")
            self.term.wait("⏎ save")
            self.term.type(typed)
            self.term.keys("Enter")
            self.term.wait(lambda screen: f"runs at once {said}" in " ".join(screen.split())
                           and "⏎ open" in screen)
            cfg = akconfig.read(self.home)
            self.assertEqual(cfg["machines"]["acme-self"].get("max_runs"), number)
            self.assertEqual((cfg["max_runs"], cfg["machines"]["acme-other"]["max_runs"]), (5, 7))
        self.assertNotIn("runs at once", self.admitted())
        self.term.keys("Escape", "Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)


if __name__ == "__main__":
    unittest.main()
