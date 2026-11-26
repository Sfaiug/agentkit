"""A listed machine's page shows its last 24 hours of processors under its marks: 24 marks, oldest
first, in eighths (`▁`–`█`, full at 1 or more, `·` with no reading), or `no readings yet`.
Black-box: AK_BIN under a terminal with state/readings' UTC day files."""

import json, sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

H = 3600
SAID = {"system": "Linux", "processor": "arm64", "cores": 4, "memory_mb": 8192, "free_mb": 4096,
        "disk_free_mb": 102400, "battery": 0, "power": 1}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AMachinesPageShowsItsLast24Hours(unittest.TestCase):
    def setUp(self):
        self.home, self.now = Home(), time.time()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        self.config = akconfig.write(self.home, ["fable"], extra="[machines.acme-linux]\n")

    def keep(self, at, who, load):
        folder = self.home.path / ".agentkit/state/readings"
        folder.mkdir(parents=True, exist_ok=True)
        tag = {"machine": who} if isinstance(who, str) else who
        with (folder / time.strftime("%Y-%m-%d.jsonl", time.gmtime(at))).open("ab") as file:
            file.write(("\n" + json.dumps({"at": at, **tag, **SAID, "load": load}) + "\n").encode())

    def open_machine(self, *expect):
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40), env={"NO_COLOR": "1"})
        for wait, keys in (("esc leave", ("c",)),
                           (lambda s: "agentkit · config " in s and "Machines" in s, ("Down",) * 5),
                           ("› Machines", ("Enter",)), ("config · machines", ("Down",)), ("› acme-linux", ("Enter",))):
            self.term.wait(wait)
            self.term.keys(*keys)
        return self.term.wait(lambda s: "config · machines · acme-linux" in s and "esc back" in s
                              and all(text in " ".join(s.split()) for text in expect))

    def test_busy_idle_and_empty_hours_show_under_the_marks_and_keys_do_nothing(self):
        before = self.config.read_bytes()
        for offset, who, load in (
            (25 * H + 1800, "acme-linux", 8.0), (23 * H + 1800, "acme-linux", 0.0),
            (18 * H + 1800, "acme-other", 8.0), (18 * H + 1800, {"home": "acme-linux"}, 8.0),
            (12 * H + 1800, "acme-linux", 1.0), (12 * H + 1200, "acme-linux", 3.0),
            (2 * H + 1800, "acme-linux", 3.9), (H + 1800, "acme-linux", 4.0), (1800, "acme-linux", 6.0),
        ):
            self.keep(self.now - offset, who, load)
        today = self.home.path / ".agentkit/state/readings" / time.strftime("%Y-%m-%d.jsonl", time.gmtime(self.now))
        with today.open("ab") as file:
            file.write(b'{"at": 1, "machine": "acme-linux", "cor')
        marks = "▁" + "·" * 10 + "▄" + "·" * 9 + "▇██"
        flat = " ".join(self.open_machine("builds and reviews", "tests", f"last 24 hours {marks}").split())
        self.assertLess(flat.index("tests"), flat.index(f"last 24 hours {marks}"))
        self.term.keys("Down", "Down", "Down")
        keys = next(line for line in reversed(self.term.wait("› last 24 hours").splitlines()) if line.strip())
        self.assertTrue("⏎" not in keys and "␣" not in keys, keys)
        self.term.keys("Enter", "Space")
        self.term.wait("› last 24 hours")
        self.assertEqual(self.config.read_bytes(), before)
        self.term.resize(40, 30)
        narrow = self.term.wait(lambda s: "─" * 40 in s and marks in s)
        self.assertTrue(all(len(line) <= 40 for line in narrow.splitlines()))
        self.term.keys("Escape", "Escape", "Escape", "Escape")
        self.assertEqual((self.term.exit_code(), self.home.calls("ssh")), (0, []))

    def test_no_readings_says_no_readings_yet(self):
        self.open_machine("builds and reviews", "tests", "last 24 hours no readings yet")
        self.term.keys("Escape", "Escape", "Escape", "Escape")
        self.assertEqual((self.term.exit_code(), self.home.calls("ssh")), (0, []))


if __name__ == "__main__":
    unittest.main()
