"""An `ak worker` turn writes only its workspace, its out directory and its harness's state.

A worker runs a model's commands on the owner's machine.  Anywhere else under HOME or the root a
write fails, and the host's files stay as they were.  `/tmp`, `/var/tmp` and `/dev/shm` are the
turn's own: empty when it starts, and what it leaves there reaches neither the host nor the next
turn.  No socket the host listens on in those places or its runtime directory answers, while
names resolve as on the host.  What the turn writes in its own places, who it runs as and the
environment it was given are what the host sees.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, with a scripted harness from fakeadapter.py whose
`sh` step runs PROBE inside each turn; the class skips where bubblewrap cannot box one.
"""

import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REPO, Home, boxable

TEMPORARY = ("/tmp", "/var/tmp", "/dev/shm")

# Run inside the turn, from its workspace, with the plan the test wrote; writes what it found.
PROBE = r'''import json, os, socket, sys
from pathlib import Path
plan = json.loads(Path(sys.argv[1]).read_text())
seen = {"temporary": {place: os.listdir(place) for place in plan["temporary"]}}


def write(path, mode="w"):
    try:
        with open(path, mode) as file:
            file.write("turn\n")
        return "written"
    except OSError:
        return "refused"


def reach(path):
    # Unix socket names are short, and the host's may be deep: connect from beside it.
    here = os.getcwd()
    try:
        os.chdir(Path(path).parent)
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(Path(path).name)
        return True
    except OSError:
        return False
    finally:
        os.chdir(here)


seen["writes"] = {path: write(path, mode) for path, mode in plan["writes"]}
seen["own"] = {path: write(path) for path in plan["own"]}
seen["left"] = {path: write(path) for path in plan["left"]}
seen["sockets"] = {path: reach(path) for path in plan["sockets"]}
mine = Path(plan["mine"])
with socket.socket(socket.AF_UNIX) as server:
    server.bind(str(mine))
    server.listen(1)
    seen["its own socket"] = reach(mine)
seen["names"] = sorted(map(repr, socket.getaddrinfo("localhost", 80, type=socket.SOCK_STREAM)))
seen["resolver"] = [Path(path).read_text() if Path(path).exists() else None
                    for path in ("/etc/hosts", "/etc/resolv.conf")]
seen["identity"] = [os.getuid(), os.getgid(), os.environ.get("HOME"), os.getcwd()]
seen["token"] = os.environ.get("ACME_PROVIDER_TOKEN")
Path(sys.argv[2]).write_text(json.dumps(seen))
'''


def resolved():
    """What the host resolves `localhost` to, and its resolver files, as PROBE reads them."""
    return (sorted(map(repr, socket.getaddrinfo("localhost", 80, type=socket.SOCK_STREAM))),
            [Path(path).read_text() if Path(path).exists() else None
             for path in ("/etc/hosts", "/etc/resolv.conf")])


@unittest.skipUnless(boxable(), "no bwrap able to box a turn here")
class WorkerBoxWrites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The Home outside the turn's temporary places, so the turn sees the real HOME, read-only,
        # not a skeleton of its own places in an empty /var/tmp.
        outside = tempfile.TemporaryDirectory(prefix=".ak-test-key-worker-box-", dir=REPO)
        cls.addClassCleanup(outside.cleanup)
        before, tempfile.tempdir = tempfile.tempdir, outside.name
        try:
            cls.home = home = Home()
        finally:
            tempfile.tempdir = before
        cls.addClassCleanup(home.close)
        akconfig.write(home, {"beta": {"harness": "acme", "model": "beta-1", "effort": "low"}})
        cls.fake = fakeadapter.install(home, acme="pass")["acme"]
        cls.ws = home.path / "code" / "widgets"
        cls.ws.mkdir(parents=True)
        cls.gitconfig = (home.path / ".gitconfig").read_text()
        cls.elsewhere = home.root / "elsewhere"
        cls.elsewhere.mkdir()
        cls.tag = tag = home.root.name
        # What the host keeps in the temporary places, and the sockets it listens on there and
        # in its runtime directory.
        cls.host = []
        for place in (*TEMPORARY, home.env["XDG_RUNTIME_DIR"]):
            directory = Path(place, f"{tag}-host")
            directory.mkdir()
            cls.addClassCleanup(shutil.rmtree, directory, True)
            (directory / "file").write_text("host\n")
            server = socket.socket(socket.AF_UNIX)
            here = os.getcwd()
            os.chdir(directory)
            try:
                server.bind("s")
            finally:
                os.chdir(here)
            server.listen(8)
            cls.addClassCleanup(server.close)
            cls.host.append(str(directory / "s"))
        cls.out = [home.path / "out" / str(n) for n in (1, 2)]
        cls.seen = []
        task = home.write("probe.md", "Probe the box.\n")
        probe = cls.fake.dir / "probe.py"
        probe.write_text(PROBE)
        for n, out in enumerate(cls.out, 1):
            plan = cls.fake.dir / f"plan-{n}.json"
            plan.write_text(json.dumps({
                "temporary": TEMPORARY,
                "writes": [[str(home.path / f".turn-{n}-wrote"), "w"],
                           [str(home.path / ".gitconfig"), "a"],
                           [str(cls.elsewhere / "turn-wrote"), "w"],
                           [f"/{tag}-turn-wrote", "w"]],
                "own": [str(cls.ws / f"made-{n}.txt"), str(out / "made.txt"),
                        str(cls.fake.dir / f"made-{n}.txt")],
                "left": [f"{place}/{tag}-left-{n}" for place in TEMPORARY],
                "sockets": cls.host, "mine": f"/tmp/{tag}-{n}.sock"}))
            seen = cls.fake.dir / f"seen-{n}.json"
            cls.fake.behave({**fakeadapter.PASS, "sh": shlex.join(
                [sys.executable, "-I", str(probe), str(plan), str(seen)])})
            done = home.ak("worker", "beta", str(task), "--workspace", str(cls.ws),
                           "--out", str(out), env={"ACME_PROVIDER_TOKEN": "fixture-provider"})
            assert done.code == 0 and seen.exists(), (done.code, done.out, done.err)
            cls.seen.append(json.loads(seen.read_text()))

    def test_a_write_outside_its_own_places_fails_and_the_host_s_files_stay(self):
        for seen in self.seen:
            self.assertEqual(set(seen["writes"].values()), {"refused"}, seen["writes"])
        for path in (*(self.home.path / f".turn-{n}-wrote" for n in (1, 2)),
                     self.elsewhere / "turn-wrote", Path(f"/{self.tag}-turn-wrote")):
            with self.subTest(path=str(path)):
                self.assertFalse(path.exists())
        self.assertEqual((self.home.path / ".gitconfig").read_text(), self.gitconfig)

    def test_temporary_places_start_empty_and_what_a_turn_leaves_there_stays_its_own(self):
        for n, seen in enumerate(self.seen, 1):
            with self.subTest(turn=n):
                # Neither the host's files nor the first turn's leftovers are there.
                self.assertEqual(seen["temporary"], dict.fromkeys(TEMPORARY, []))
                self.assertEqual(set(seen["left"].values()), {"written"}, seen["left"])
                for place in TEMPORARY:
                    self.assertFalse(Path(place, f"{self.tag}-left-{n}").exists(), place)
                self.assertFalse(Path(f"/tmp/{self.tag}-{n}.sock").exists())

    def test_no_host_socket_answers_and_names_resolve_as_on_the_host(self):
        for seen in self.seen:
            self.assertEqual(seen["sockets"], dict.fromkeys(self.host, False))
            self.assertTrue(seen["its own socket"])
            self.assertEqual([seen["names"], seen["resolver"]], list(resolved()))
        # The host's sockets were there all along: the host still reaches each.
        for path in self.host:
            with self.subTest(path=path), socket.socket(socket.AF_UNIX) as client:
                here = os.getcwd()
                os.chdir(Path(path).parent)
                try:
                    client.connect("s")
                finally:
                    os.chdir(here)

    def test_its_own_writes_identity_and_environment_are_what_the_host_sees(self):
        for n, seen in enumerate(self.seen, 1):
            with self.subTest(turn=n):
                self.assertEqual(set(seen["own"].values()), {"written"}, seen["own"])
                for path in seen["own"]:
                    self.assertEqual(Path(path).read_text(), "turn\n", path)
                    self.assertEqual(Path(path).stat().st_uid, os.getuid(), path)
                self.assertEqual(seen["identity"], [os.getuid(), os.getgid(),
                                                    str(self.home.path), str(self.ws)])
                self.assertEqual(seen["token"], "fixture-provider")


if __name__ == "__main__":
    unittest.main()
