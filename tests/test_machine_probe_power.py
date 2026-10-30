"""On Linux the probe (tools/machine.sh) says whether the machine has a battery and is on power
now: a charger's own `online` first, else every battery's status, and never a mouse's battery.
Each case runs the probe in a bubblewrap box whose /sys/class/power_supply holds only its own.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
BATTERY = {"type": "Battery", "scope": "System"}
OFFLINE, ONLINE = {"type": "Mains", "online": "0"}, {"type": "Mains", "online": "1"}
CASES = {     # the supplies, then what the probe says: (battery, power)
    "status unknown, charger offline": ({"BAT0": {**BATTERY, "status": "Unknown"},
                                         "AC": OFFLINE}, ("1", "0")),
    "status unknown, charger online": ({"BAT0": {**BATTERY, "status": "Unknown"},
                                        "AC": ONLINE}, ("1", "1")),
    "discharging, no charger listed": ({"BAT0": {**BATTERY, "status": "Discharging"}}, ("1", "0")),
    "held below full, no charger listed": ({"BAT0": {**BATTERY, "status": "Not charging"}},
                                           ("1", "1")),
    "one pack discharging, the other full": ({"BAT0": {**BATTERY, "status": "Discharging"},
                                              "BAT1": {**BATTERY, "status": "Full"}}, ("1", "0")),
    "charging, programmable supply online": ({"BAT0": {**BATTERY, "status": "Charging"},
                                              "USB": {"type": "USB", "scope": "System",
                                                      "online": "2"}}, ("1", "1")),
    "a mouse's battery only": ({"hid-mouse": {"type": "Battery", "scope": "Device",
                                              "status": "Discharging"}}, ("0", "1")),
    "no supply at all": ({}, ("0", "1")),
}


@unittest.skipUnless(shutil.which("bwrap"), "no bwrap to give the probe supplies of its own")
class ProbePower(unittest.TestCase):
    def test_battery_and_power_by_the_supplies(self):
        for case, (supplies, expected) in CASES.items():
            with self.subTest(case), tempfile.TemporaryDirectory() as scratch:
                for name, values in supplies.items():
                    (Path(scratch) / name).mkdir()
                    for key, value in values.items():
                        (Path(scratch) / name / key).write_text(value + "\n")
                done = subprocess.run(
                    ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/sys",
                     "--ro-bind", scratch, "/sys/class/power_supply", "--",
                     "bash", str(REPO / "tools" / "machine.sh")],
                    env={"HOME": scratch, "PATH": "/usr/bin:/bin"}, capture_output=True,
                    text=True, timeout=30)
                self.assertEqual(done.returncode, 0, done.stderr)
                said = dict(line.split(" ", 1) for line in done.stdout.splitlines())
                self.assertEqual((said["battery"], said["power"]), expected)


if __name__ == "__main__":
    unittest.main()
