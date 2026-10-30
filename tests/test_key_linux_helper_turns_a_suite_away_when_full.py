"""A Linux suite helper admits a suite at its `prepare` while a quarter of the machine is spare,
counting half of it for each suite admitted whose first piece does not run yet, and gives one
suite at most half of it; one image's build holds up no other's.

Black-box, as tests/test_key_helper_on_linux.py: tools/helper's script runs here as ak sends it,
in a HOME of its own, with the machine's programs first on PATH: four CPUs, each counting twice
as a piece holds half what it is given, 64 GiB and a fake docker.
"""

import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "helper"
IMAGE = "ak-helper-acme:0123456789ab"
OTHER = "ak-helper-widgets:ba9876543210"

# docker, as tools/helper/linux.sh asks it: images and containers are files under the machine's
# `docker`, a container's holding the CPUs and bytes it was given; one `run` leaves `asked`,
# starts once `starting` is gone and ends as it starts; with `together`, a build ends once another
# has started.
DOCKER = r"""#!/bin/bash
cd "$(dirname "$0")/../docker" || exit 1
case $1 in
build)    # build -q -t IMAGE -f RECIPE CONTEXT
  : >"started-$4"
  while [ -e together ] && [ "$(ls started-* | wc -l)" -lt 2 ]; do sleep 0.1; done
  touch "images/$4" ;;
image) [ "$2" != inspect ] || [ -e "images/$3" ] ;;
run) : >asked; while [ -e starting ]; do sleep 0.1; done ;;
ps) ls containers ;;
inspect)    # inspect --format FORMAT NAME...: an unknown container fails it, as docker's does
  for name in "${@:4}"; do
    read -r cpus bytes <"containers/$name" || exit 1
    case $3 in *NanoCpus*) echo "$cpus" ;; *Memory*) echo "$bytes" ;; *) echo true ;; esac
  done ;;
esac
"""

MACHINE = {"docker": DOCKER, "nproc": "#!/bin/sh\necho 4\n",
           "free": "#!/bin/sh\nprintf '%s\\n' '  total used' 'Mem: 65536 1024'\n"}


class LinuxHelperTurnsASuiteAway(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-linux-helper-")
        self.addCleanup(tmp.cleanup)
        self.machine = Path(tmp.name)
        for directory in ("home", "bin", "docker/images", "docker/containers", "repo"):
            (self.machine / directory).mkdir(parents=True)
        for name, text in MACHINE.items():
            (self.machine / "bin" / name).write_text(text)
            (self.machine / "bin" / name).chmod(0o755)
        repo = self.machine / "repo"
        git = ["env", "GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_NOSYSTEM=1", "git", "-C",
               str(repo), "-c", "user.name=acme", "-c", "user.email=a@acme.test"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "start"], check=True)
        subprocess.run([*git, "bundle", "create", "-q", "repo.bundle", "HEAD"], check=True)
        self.parcel = io.BytesIO()
        with tarfile.open(fileobj=self.parcel, mode="w") as tar:
            for name, data in (("image/Containerfile", b"FROM docker.io/library/alpine:3.20\n"),
                               ("heads", subprocess.run([*git, "rev-parse", "HEAD"], check=True,
                                                        capture_output=True).stdout),
                               ("repo.bundle", (repo / "repo.bundle").read_bytes())):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

    def helper(self, verb, *args):
        script = (TOOLS / "linux.sh").read_text() + (TOOLS / "mac.sh").read_text()
        return subprocess.run(
            ["bash", "-c", script, "mac.sh", verb, *args], input=self.parcel.getvalue(),
            capture_output=True, timeout=60,
            env={"HOME": str(self.machine / "home"),
                 "PATH": f"{self.machine / 'bin'}:/usr/bin:/bin"})

    def readings(self):
        probe = self.helper("probe")
        self.assertEqual(probe.returncode, 0, probe.stderr)
        return dict(line.split() for line in probe.stdout.decode().splitlines())

    def probe(self):
        """(CPUs spare for a suite, the most one gets), as `probe` answers."""
        readings = self.readings()
        return float(readings["cpus"]) - float(readings["load"]), float(readings["cpus"])

    def prepare(self, key):
        return self.helper("prepare", key, IMAGE, "acme").returncode

    def running(self, name, cpus, gib=1):
        """A piece of another suite runs there, given `cpus` CPUs and `gib` GiB."""
        (self.machine / "docker/containers" / name).write_text(f"{cpus}000000000 {gib << 30}\n")

    def test_two_suites_fill_an_empty_machine_until_one_starts_a_piece(self):
        self.assertEqual(self.probe(), (4, 4))
        self.assertEqual((self.prepare("a"), self.prepare("b")), (0, 0))
        self.assertEqual(self.probe(), (0, 4))
        state = self.machine / "docker"
        (state / "starting").touch()
        with ThreadPoolExecutor() as pool:
            run = pool.submit(self.helper, "run", "a", IMAGE, "ak-a-1-1", "2", "1024", "acme",
                              "1/1", "", "", "", "true")
            deadline = time.monotonic() + 30
            while not (state / "asked").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(self.prepare("c"), 252)    # a's piece starts: a holds its half
            (state / "starting").unlink()
            self.assertEqual(run.result().returncode, 0, run.result().stderr)
        self.assertEqual(self.prepare("c"), 0)
        self.assertEqual(self.prepare("d"), 252)

    def test_one_image_s_build_holds_up_no_other_image_s(self):
        (self.machine / "docker/together").touch()
        with ThreadPoolExecutor() as pool:
            suites = [pool.submit(self.helper, "prepare", key, image, name)
                      for key, image, name in (("a", IMAGE, "acme"), ("b", OTHER, "widgets"))]
            self.assertEqual([suite.result().returncode for suite in suites], [0, 0])
        self.assertEqual(sorted(path.name for path in (self.machine / "docker/images").iterdir()),
                         [IMAGE, OTHER])

    def test_a_running_piece_counts_the_whole_memory_it_was_given(self):
        self.running("ak-other-1-2", 1, 40)    # the machine holds 1 GiB: the piece may grow to 40
        self.assertEqual(self.readings()["room_mb"], "18022")

    def test_a_suite_that_starts_no_piece_holds_nothing_two_minutes_on(self):
        self.assertEqual((self.prepare("a"), self.prepare("b"), self.prepare("c")), (0, 0, 252))
        then = time.time() - 180
        for path in (self.machine / "home").rglob("*"):
            os.utime(path, (then, then), follow_symlinks=False)
        self.assertEqual(self.prepare("c"), 0)

    def test_running_containers_hold_the_cpus_they_were_given(self):
        self.running("ak-other-1-2", 3)
        self.assertEqual(self.probe(), (4, 4))
        self.running("ak-other-2-2", 3)
        self.assertEqual(self.probe(), (2, 4))
        self.assertEqual((self.prepare("a"), self.prepare("b")), (0, 252))


if __name__ == "__main__":
    unittest.main()
