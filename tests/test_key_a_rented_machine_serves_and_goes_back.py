"""A machine ak rents serves suites once ready and goes back once it has held nothing for ten
minutes; one not ready is left alone; one that served and stops answering keeps its route for the
work it holds but takes no new work; with `[google_cloud]` not active, none serves or goes back.

Black-box: `AK_BIN` runs `ak watch` in `home.tick()`'s box, `ak doctor` and a lander against the
fake Google of tests/fixtures/google.py.  A fake ssh is the machines, each a directory named by its
address with tests/fixtures/akmachine.py's programs, /run/ak-ready and /proc/uptime of its own,
reached only where the real `ssh -G`, connecting to nothing, reads ak's options as ak by ak's key.
"""

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akmachine
from fixtures.akbin import REPO, Home, boxable
from fixtures.akline import Line
from fixtures.google import ADDRESS, NL, SPOT, Google, kind, sku

SKUS = [sku(f"{SPOT} C4A Arm Instance Core running in Netherlands", NL, 700_000_000),
        sku(f"{SPOT} C4A Arm Instance Ram running in Netherlands", NL, 12_500_000),
        sku("Hyperdisk Balanced Capacity in Netherlands", NL, 73_000_000, "GiBy.mo"), ADDRESS]
REAL_SSH = shutil.which("ssh", path="/usr/bin:/bin")
HELPER = "".join((REPO / "tools/helper" / name).read_text() for name in ("linux.sh", "mac.sh"))
SSH = """#!{python}
import os, pathlib, subprocess, sys
*options, host, line = sys.argv[1:]
# the system's config, which ssh refuses to read in a tick's box, only where ak hands none
config = () if "-F" in options else ("-F", "none")
seen = subprocess.run([{ssh!r}, "-G", *config, *options, host], capture_output=True, text=True)
seen = seen.stdout.splitlines()
machine = pathlib.Path({machines!r}, next((one[9:] for one in seen if one[:9] == "hostname "), "-"))
if not {{"user ak", "identityfile {key}"}} <= set(seen) or not machine.is_dir():
    sys.exit(255)
(machine / "reached").touch()
for path in ("/run/ak-ready", "/proc/uptime"):
    line = line.replace(path, f"{{machine}}{{path}}")
os.execve("/bin/bash", ["bash", "-c", line],
          {{"HOME": f"{{machine}}/home", "PATH": f"{{machine}}/bin:/usr/bin:/bin"}})
"""


def listed(n):
    return {"id": str(n), "name": f"acme-{n}", "labels": {"ak": "rented"},
            "creationTimestamp": datetime.fromtimestamp(time.time() - 60, UTC).isoformat(),
            "machineType": "zones/europe-west4-a/machineTypes/c4a-standard-8",
            "scheduling": {"maxRunDuration": {"seconds": "21600"}},
            "networkInterfaces": [{"accessConfigs": [{"natIP": f"203.0.113.{n}"}]}]}


@unittest.skipUnless(boxable() and REAL_SSH, "no bwrap able to box a tick, or no ssh, here")
class ARentedMachineServesAndGoesBack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.google = google = Google(home, [SKUS], [{"zones/europe-west4-a": {
            "machineTypes": [kind("c4a-standard-8", 8, 32)]}}])
        cls.addClassCleanup(google.close)
        google.key()
        cls.machines, cls.toml = home.root / "machines", home.path / ".agentkit/config.toml"
        cls.key = home.path / ".agentkit/secrets/google-cloud-ssh"
        home.fake("ssh", SSH.format(python=sys.executable, machines=str(cls.machines),
                                    ssh=REAL_SSH, key=cls.key))
        cls.active(True)
        cls.tick()      # the prices a machine is metered at
        # 1 holds a container, 2 held nothing 11 minutes, 3 and 4 never ran, up 5 and 11
        # minutes, 5 receives a suite, 6 is not ready and 7's docker does not answer, then 7 not at all
        for n, up, ago in ((1, 3600, 1200), (2, 3600, 660), (3, 300, None), (4, 660, None),
                           (5, 3600, None), (6, 3600, None), (7, 3600, 1200)):
            cls.machine(n, up, ago, ready=n != 6)
        (cls.machines / "203.0.113.1/docker/containers/ak-a-1-1").write_text("1073741824\n")
        (cls.machines / "203.0.113.7/bin/docker").write_text("#!/bin/sh\nexit 1\n")
        five = cls.machines / "203.0.113.5"
        prepare = subprocess.Popen(["bash", "-c", HELPER, "mac.sh", "prepare", "a", "ak-helper-a:b",
                                    "acme"], stdin=subprocess.PIPE, env={
            "HOME": f"{five}/home", "PATH": f"{five}/bin:/usr/bin:/bin"})
        deadline = time.monotonic() + 60
        while subprocess.run(["flock", "-n", f"{five}/home/.agentkit-helper/a/preparing", "true"],
                             stderr=subprocess.DEVNULL).returncode != 1:
            assert time.monotonic() < deadline and prepare.poll() is None, "prepare never held 5"
            time.sleep(0.05)
        os.utime(five / "home/.agentkit-helper", (time.time() - 1200,) * 2)
        google.machines = [listed(n) for n in range(1, 8)]
        cls.first = cls.tick()
        prepare.communicate()   # an empty parcel: the suite goes
        # a host key at each of 1's and 6's addresses: 1 serves, 6 does not yet
        known = home.path / ".agentkit/secrets/google-cloud-known-hosts"
        cls.host_key = " ".join(Path(f"{cls.key}.pub").read_text().split()[:2])
        known.write_text("".join(f"203.0.113.{n} {cls.host_key}\n" for n in (1, 6)))
        google.machines = [listed(n) for n in (1, 3, 5, 6, 7)]
        (cls.machines / "203.0.113.7").rename(cls.machines / "silent")
        cls.second, cls.known = cls.tick(), known.read_text()
        cls.route = subprocess.run([REAL_SSH, "-G", "-F", home.path / ".agentkit/state/google-cloud-"
                                    "ssh-config", "acme-7"], capture_output=True, text=True).stdout
        line = Line({"t/a.sh": "true\n", "tools/helper/Containerfile": "FROM acme\n"}, home=home)
        line.member({"api.txt": "x\n"})
        cls.landed, cls.verdict = line.land(), line.verdict(1)
        (cls.machines / "203.0.113.3/proc/uptime").write_text("660.00 1.00\n")
        cls.active(False)
        (cls.machines / "203.0.113.1/reached").unlink()
        cls.off, cls.reached_off = cls.tick(), (cls.machines / "203.0.113.1/reached").exists()

    @classmethod
    def active(cls, on):
        """Off, the owner's own suite helper has the name of one ak rented."""
        cls.toml.write_text('suite_helper = "acme-1"\n' * (not on) +
                            cls.toml.read_text().split("\n[google_cloud]")[0] +
                            f"\n[google_cloud]\nactive = {str(on).lower()}\nmax_month = 50\n")

    @classmethod
    def machine(cls, n, up, ago, ready):
        machine = cls.machines / f"203.0.113.{n}"
        for directory in ("home", "bin", "docker/images", "docker/containers", "run", "proc"):
            (machine / directory).mkdir(parents=True)
        for name, text in akmachine.TOOLS.items():
            (machine / "bin" / name).write_text(text)
            (machine / "bin" / name).chmod(0o755)
        (machine / "proc/uptime").write_text(f"{up}.00 1.00\n")
        if ready:
            (machine / "run/ak-ready").touch()
        if ago:
            (root := machine / "home/.agentkit-helper").mkdir()
            os.utime(root, (time.time() - ago,) * 2)

    @classmethod
    def tick(cls):
        """Whom a tick gave back, the machines `ak doctor` shows answering, its rented lines."""
        start, done = len(cls.google.asked), cls.home.tick(env=cls.google.env)
        assert done.code == 0, done.out + done.err
        doctor = cls.home.ak("doctor", env=cls.google.env)
        assert doctor.code == 0, doctor.out + doctor.err
        lines = doctor.out.splitlines()
        return ([one[7:] for one in cls.google.asked[start:] if one.startswith("DELETE ")],
                [line[9:].split(":")[0] for line in lines
                 if line.startswith("machine  ") and not line.endswith("never answered")],
                [line[17:] for line in lines if line.startswith("rented machines: ")][1:])

    def test_a_ready_machine_serves_until_it_held_nothing_ten_minutes(self):
        self.assertEqual(self.first, (["acme-2", "acme-4"], [
            "this one", "acme-1", "acme-3", "acme-5", "acme-7"], [
            "acme-2 listed idle, given back", "acme-4 listed idle, given back"]))
        # its suite gone, 5 has held nothing 20 minutes
        self.assertEqual(self.second, (["acme-5"], ["this one", "acme-1", "acme-3"],
                                       ["acme-5 listed idle, given back"]))

    def test_the_address_of_one_not_serving_yet_is_forgotten_before_ssh_asks_it(self):
        self.assertEqual(self.known, f"203.0.113.1 {self.host_key}\n")

    def test_one_serving_that_stops_answering_keeps_its_route_and_takes_no_new_work(self):
        self.assertIn("hostname 203.0.113.7\n", self.route)
        self.assertNotIn("acme-7", self.second[1])

    def test_a_suite_goes_to_one(self):
        self.assertEqual(self.landed.code, 0, self.landed.out + self.landed.err)
        self.assertIn("land", self.verdict)
        self.assertIn("suite on acme-1:", self.landed.out + self.landed.err)

    def test_not_active_none_serves_or_goes_back(self):
        # the owner's own acme-1 shows what it last answered, and ssh takes it there no more
        self.assertEqual((self.off, self.reached_off), (([], ["this one", "acme-1"], []), False))


if __name__ == "__main__":
    unittest.main()
