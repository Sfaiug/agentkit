"""A listed machine's page says, after its 24 marks, what those 24 hours ran short of:
`short of processors in N of 24 hours`, `short of memory in N of 24 hours`, both joined by ` · `,
or `never short`, and nothing more after `no readings yet`.
Black-box: AK_BIN under a terminal with state/readings' UTC day files."""

import json, sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

H, TENTH = 3600, 360_000_000
LINUX = {"system": "Linux", "processor": "arm64", "cores": 4, "memory_mb": 8192, "free_mb": 4096,
         "disk_free_mb": 102400, "battery": 0, "power": 1}
MAC = {**LINUX, "system": "macOS"}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AMachinesPageSaysWhatItRanShortOf(unittest.TestCase):
    def setUp(self):
        self.home, self.now = Home(), time.time()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        extra = "".join(f"[machines.{name}]\n"
                        for name in ("acme-both", "acme-mem", "acme-mac", "acme-calm", "acme-empty"))
        akconfig.write(self.home, ["fable"], extra=extra)

    def keep(self, offset, machine, load, stall=None, base=LINUX):
        at = self.now - offset
        folder = self.home.path / ".agentkit/state/readings"
        folder.mkdir(parents=True, exist_ok=True)
        row = {"at": at, "machine": machine, **base, "load": load}
        if stall is not None:
            row["memory_stall_us"] = stall
        with (folder / time.strftime("%Y-%m-%d.jsonl", time.gmtime(at))).open("ab") as file:
            file.write(("\n" + json.dumps(row) + "\n").encode())

    def test_page_says_shortages_restart_clamping_mac_never_short_and_empty(self):
        # acme-both: 2 hours load > cores (1 at load == cores does not count), 1 hour with a tenth
        # of memory wait, and 1 hour whose counter drops (restart -> no wait).
        for offset, load, stall in (
            (5 * H + 1800, 4.0, 900_000_000), (5 * H + 1200, 4.0, 100_000_000),  # restart, load == cores
            (3 * H + 1800, 2.0, 100_000_000), (3 * H + 1200, 2.0, 100_000_000 + TENTH),  # short of memory
            (2 * H + 1800, 6.0, 100_000_000 + TENTH), (H + 1800, 8.0, 100_000_000 + TENTH),  # short of cpu
        ):
            self.keep(offset, "acme-both", load, stall)
        # acme-mem: cross-hour tenth counts for the later hour; 60s jump of 500s clamps to 60s (< tenth).
        for offset, load, stall in (
            (3 * H + 200, 1.0, 1_000_000), (3 * H - 200, 1.0, 1_000_000 + TENTH),
            (H + 3000, 1.0, 1_000_000 + TENTH), (H + 2940, 1.0, 501_000_000 + TENTH),
        ):
            self.keep(offset, "acme-mem", load, stall)
        # acme-mac: no memory_stall_us -> never short of memory; 1 hour load > cores.
        self.keep(1800, "acme-mac", 6.0, base=MAC)
        # acme-calm: readings present, load <= cores, counter falls and stays flat -> never short.
        for offset, stall in ((2 * H + 1800, 500_000_000), (H + 1800, 10_000), (1800, 10_000)):
            self.keep(offset, "acme-calm", 2.0, stall)

        term = Terminal(self.home, "attach", "--overlay", size=(120, 40), env={"NO_COLOR": "1"})
        for wait, keys in (("esc leave", ("c",)),
                           (lambda s: "agentkit · config " in s and "Machines" in s, ("Down",) * 5),
                           ("› Machines", ("Enter",))):
            term.wait(wait)
            term.keys(*keys)

        cases = (
            ("acme-both", "·" * 18 + "█·▄██·",
             "short of processors in 2 of 24 hours · short of memory in 1 of 24 hours"),
            ("acme-mem", "·" * 20 + "▂" * 3 + "·", "short of memory in 1 of 24 hours"),
            ("acme-mac", "·" * 23 + "█", "short of processors in 1 of 24 hours"),
            ("acme-calm", "·" * 21 + "▄" * 3, "never short"),
            ("acme-empty", "no readings yet", ""),
        )
        on_list = lambda s: "config · machines" in s and "+ add a machine" in s
        for name, head, tail in cases:
            term.wait(on_list)
            term.keys("Down")
            term.wait(f"› {name}")
            term.keys("Enter")
            screen = term.wait(lambda s, n=name, h=head: f"config · machines · {n}" in s
                               and "esc back" in s and h in s)
            flat = " ".join(screen.split())
            if tail:
                self.assertIn(f"last 24 hours {head} {tail}", flat)
            else:
                row = next(line.strip() for line in screen.splitlines() if "last 24 hours" in line)
                self.assertTrue(row.endswith("no readings yet"), row)
            if name == "acme-both":
                term.resize(40, 30)
                narrow = term.wait(lambda s, h=head: "─" * 40 in s and h in s)
                self.assertTrue(all(len(line) <= 40 for line in narrow.splitlines()))
                self.assertIn(f"last 24 hours {head} {tail}", " ".join(narrow.split()))
                term.resize(120, 40)
                term.wait(lambda s: "─" * 120 in s)
            term.keys("Escape")
        term.wait(on_list)
        term.keys("Escape", "Escape", "Escape")
        self.assertEqual((term.exit_code(), self.home.calls("ssh")), (0, []))


if __name__ == "__main__":
    unittest.main()
