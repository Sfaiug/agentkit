"""Each seat and each tmux pane holds a run's memory cap, and a runaway in one dies alone.

Offline: the `Installer` fakes from `test_slice` -- a fake `systemctl`, `nproc` and `tmux`
on PATH, a throwaway HOME -- and no real user manager.  The live mode's check installs into
a throwaway HOME the same way, then starts two throwaway scopes under `agentkit-test-cap*`,
inside `agentkit-test.slice`, with the properties that install wrote for a cap of 64 MB, on
the real manager the suite started with; the kernel's own cap ends the allocator, and the
only systemctl stop is of those names, minted here.
"""

import os
import shutil
import subprocess
import sys
import time
import unittest
import uuid

from test_slice import Installer
from test_memory_cap import ALLOCATOR

# The manager and the binaries the suite started with, before `Installer` puts its fakes on
# PATH and points the runtime directory at a socket of its own.
REAL_ENV = dict(os.environ)
REAL = {name: shutil.which(name) for name in ("systemd-run", "systemctl")}

UNITS = {"agentkit-seat-.scope": "Scope", "agentkit-seat-.service": "Service",
         "tmux-spawn-.scope": "Scope"}


def dropin(home, unit):
    return home / ".config/systemd/user" / f"{unit}.d" / "agentkit-limits.conf"


class JobCap(Installer):
    def pinned_home(self, name, cap_mb):
        home = self.root / name
        (home / ".agentkit").mkdir(parents=True)
        (home / ".agentkit/config.toml").write_text(f"run_memory_max_mb = {cap_mb}\n")
        return home

    def test_a_every_seat_and_pane_gets_a_runs_cap_and_a_quarter_of_it_in_swap(self):
        home = self.pinned_home("pinned-home", 4000)
        result = self.install(home)
        self.assertEqual(result.returncode, 0, result.stderr)
        for unit, section in UNITS.items():
            written = dropin(home, unit).read_text()
            self.assertTrue(written.startswith("# Written by agentkit's install.sh"), written)
            self.assertIn(f"[{section}]\nMemoryMax=4000M\nMemorySwapMax=1000M\n"
                          "OOMPolicy=continue\n", written)
        self.assertIn("capped at 4000M of memory and 1000M of swap", result.stdout)
        self.assertIn(["systemctl", "--user", "daemon-reload"], self.commands("systemctl"))

    def test_b_unpinned_the_cap_follows_the_slice_ceiling(self):
        home = self.root / "derived-home"
        home.mkdir()
        result = self.install(home)
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = dict(line.split("=", 1) for line in
                      dropin(home, "agentkit-seat-.scope").read_text().splitlines()
                      if "=" in line)
        cap = int(fields["MemoryMax"].removesuffix("M"))
        # 40% of the slice's 70% of whatever this host has, never the 4 GB fallback
        self.assertNotEqual(cap, 4096)
        self.assertGreater(cap, 0)
        self.assertEqual(fields["MemorySwapMax"], f"{cap // 4}M")

    def test_c_a_file_the_owner_wrote_is_left_byte_identical(self):
        home = self.pinned_home("owned-home", 4000)
        owned = dropin(home, "tmux-spawn-.scope")
        owned.parent.mkdir(parents=True)
        owned.write_text("[Scope]\nMemoryMax=12G\n")
        result = self.install(home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(owned.read_text(), "[Scope]\nMemoryMax=12G\n")
        self.assertIn("MemoryMax=4000M", dropin(home, "agentkit-seat-.scope").read_text())

    # tests/live.sh selects this explicitly; landing discovers only the fake-manager cases.
    def check_a_runaway_dies_alone_and_its_seat_and_the_next_seat_go_on(self):
        def real(*argv, timeout=10):
            return subprocess.run([REAL[argv[0]], *argv[1:]], env=REAL_ENV, timeout=timeout,
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if not all(REAL.values()) or real("systemctl", "--user", "is-system-running").stdout \
                .strip() not in ("running", "degraded"):
            self.skipTest("no user systemd manager")
        version = real("systemctl", "--user", "show", "-p", "Version", "--value").stdout
        if int(version.split(".")[0].split("-")[0] or 0) < 253:
            self.skipTest("a scope takes OOMPolicy from systemd 253")
        home = self.pinned_home("live-home", 64)
        result = self.install(home)
        self.assertEqual(result.returncode, 0, result.stderr)
        props = [arg for line in dropin(home, "agentkit-seat-.scope").read_text().splitlines()
                 if line.startswith(("Memory", "OOMPolicy")) for arg in ("-p", line)]
        self.assertEqual(props, ["-p", "MemoryMax=64M", "-p", "MemorySwapMax=16M",
                                 "-p", "OOMPolicy=continue"])
        token = f"agentkit-test-cap{os.getpid() % 100000}{uuid.uuid4().hex[:4]}"
        seats = f"{token}-seats.slice"
        runaway, neighbour = f"{token}-seat-a", f"{token}-seat-b"

        def stop():
            # Only the two scopes and the throwaway slice minted above.
            real("systemctl", "--user", "stop", f"{runaway}.scope", f"{neighbour}.scope",
                 f"{token}.slice")
            real("systemctl", "--user", "reset-failed", f"{runaway}.scope")
        self.addCleanup(stop)
        sleeper = subprocess.Popen(
            [REAL["systemd-run"], "--user", f"--slice={seats}", "--scope", "--quiet",
             f"--unit={neighbour}", *props, "--", "sleep", "30"], env=REAL_ENV,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(sleeper.wait, timeout=15)
        deadline = time.monotonic() + 5
        while real("systemctl", "--user", "is-active", f"{neighbour}.scope").stdout.strip() \
                != "active" and time.monotonic() < deadline:
            time.sleep(0.05)
        # The seat's shell stands in for its harness: it starts the job and lives on after it.
        # With OOMPolicy=stop the manager ends the whole scope moments after the kill, so the
        # shell waits two seconds before it says it went on.
        seat = real("systemd-run", "--user", f"--slice={seats}", "--scope", "--quiet",
                    f"--unit={runaway}", *props, "--", "sh", "-c",
                    '"$0" -c "$1" "$2" "$3"; echo "job $?"; sleep 2; echo "harness goes on"',
                    sys.executable, ALLOCATOR, runaway, neighbour, timeout=60)
        lines = seat.stdout.splitlines()
        self.assertTrue(lines and lines[0].startswith("armed "), seat.stdout + seat.stderr)
        self.assertIn("job 137", lines, seat.stdout)          # SIGKILL, from the kernel
        self.assertEqual(lines[-1], "harness goes on", seat.stdout)
        self.assertEqual(seat.returncode, 0, seat.stdout + seat.stderr)
        self.assertEqual(real("systemctl", "--user", "is-active", f"{neighbour}.scope")
                         .stdout.strip(), "active")
        self.assertIsNone(sleeper.poll())
        stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
