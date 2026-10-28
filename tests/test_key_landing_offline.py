"""A suite declared behind the offline wrapper runs at landing with nothing beyond its loopback.

The landing suite must judge the code alone, never what the network or the host's own services
answer that day: agentkit's `tests:` line runs it in a network namespace of its own holding
only loopback, and ak's landing must let that wrapper build its namespace, inside ak's own box.
Here a project declares its suite the same way, and the suite reports what it can reach: its
own loopback, a listener on the host's loopback, and an address outside, tried only once it
has seen that no interface but loopback exists, so no test sends a packet out.  The run lands
and the suite's report is in the run's record.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, against the bare origin of gitrig.py and the
GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
import os
import socket
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# The shape of agentkit's own `tests:` line, with its suite swapped for the project's.
LINE = ("offline() { unshare --user --map-current-user --net --keep-caps sh -c "
        "'ip link set lo up && exec setpriv --inh-caps=-all --ambient-caps=-all \"$@\"' - \"$@\"; "
        "}; offline true 2>/dev/null || { echo \"cannot build the offline sandbox\" >&2; exit 1; }; "
        "offline python3 tests/suite.py")
SUITE = """import errno, os, socket


def attempt(name, address):
    try:
        socket.create_connection(address, timeout=5).close()
        print(f"suite {name}: reached")
    except OSError as exc:
        print(f"suite {name}: {errno.errorcode.get(exc.errno, exc.errno)}")


rows = open("/proc/net/dev").read().splitlines()[2:]
interfaces = [row.split(":")[0].strip() for row in rows]
print("suite network:", os.readlink("/proc/self/ns/net"))
print("suite interfaces:", " ".join(interfaces))
# Closed before the host probe, as its port may be the host listener's number.
with socket.create_server(("127.0.0.1", 0)) as own:
    attempt("own loopback", own.getsockname())
attempt("host loopback", ("127.0.0.1", HOST_PORT))
if interfaces == ["lo"]:
    attempt("outside", ("192.0.2.1", 80))
"""


def report(run_dir):
    """The lines the suite printed, from the file of the run's record that holds them."""
    for path in sorted(run_dir.rglob("*")):
        if path.is_file():
            lines = path.read_text(errors="replace").splitlines()
            said = [line for line in lines if line.startswith("suite ")]
            if any(line.startswith("suite network: ") for line in said):
                return said
    raise AssertionError(f"nothing in {run_dir} holds what the suite printed")


class LandingOffline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        # A service of the host's own, such as a browser's debugging port, listens on loopback.
        cls.listener = socket.create_server(("127.0.0.1", 0))
        cls.addClassCleanup(cls.listener.close)
        port = cls.listener.getsockname()[1]
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": f"---\ntests: {LINE}\n---\n# widgets\n",
            "tests/suite.py": SUITE.replace("HOST_PORT", str(port))})
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.said = report(cls.run_dir)

    def test_the_run_lands_with_the_declared_suite_passed_at_landing(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in ("verdict", "merged")},
                         {"verdict": "PASS", "merged": True})
        self.assertEqual({key: self.state["final_check"].get(key) for key in (
            "outcome", "where", "suite")}, {"outcome": "passed", "where": "landing",
                                            "suite": LINE})
        self.assertIn("retry.txt", self.rig.files())

    def test_the_suite_runs_in_a_network_of_its_own_holding_only_loopback(self):
        self.assertIn("suite interfaces: lo", self.said)
        network = [line for line in self.said if line.startswith("suite network: ")]
        self.assertEqual(len(network), 1, self.said)
        self.assertNotEqual(network[0].split(": ", 1)[1], os.readlink("/proc/self/ns/net"))

    def test_its_own_loopback_is_up_and_the_outside_is_unreachable(self):
        self.assertIn("suite own loopback: reached", self.said)
        self.assertIn("suite outside: ENETUNREACH", self.said)

    def test_a_listener_on_the_host_s_loopback_is_out_of_its_reach(self):
        self.assertIn("suite host loopback: ECONNREFUSED", self.said)
        self.listener.setblocking(False)
        with self.assertRaises(BlockingIOError):
            self.listener.accept()[0].close()


if __name__ == "__main__":
    unittest.main()
