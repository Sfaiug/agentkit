"""A suite the helper has room for runs there alone, though this host has turns free; and while
one it has no room for waits for a turn here, a new run starts all the same.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py; the helper is a fake ssh with room for two VMs, whose pieces pass there.
"""

import fcntl
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akline import Line

# The words after the alias are one `bash -c <mac.sh> mac.sh <verb> ...` line.
SSH = f"""#!{sys.executable}
import shlex, sys
words = shlex.split(sys.argv[-1])
verb = words[words.index("mac.sh") + 1]
if verb == "probe":
    print("cpus 4\\nload 0\\nroom_mb 65536")
elif verb == "prepare":
    sys.stdin.buffer.read()
"""


class SuiteOnAHelper(unittest.TestCase):
    def test_no_piece_of_it_runs_here(self):
        line = Line({"t/a.sh": "true\n", "t/b.sh": "true\n",
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        line.home.env["AK_MAX_RUNS"] = ""    # this host has turns to give
        line.home.fake("ssh", SSH)
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(1))
        self.assertEqual(line.runs(), [])

    def test_a_clone_borrowing_a_repository_s_objects_names_its_copy_there(self):
        files = {"t/a.sh": "true\n", "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"}
        line = Line(files)
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        names = line.home.root / "names"
        line.home.fake("ssh", SSH.replace("    sys.stdin.buffer.read()\n", f"""    sys.stdin.buffer.read()
    open({str(names)!r}, "a").write(words[words.index("mac.sh") + 4] + "\\n")\n"""))
        checkout, origin = line.rig.path, str(line.rig.bare)

        def landed_from(name, *clone):
            if clone:
                line.line, line.rig.path = f".merge-{name}.lock", checkout.parent / name
                line.home.run("git", "clone", "-q", *clone, str(line.rig.path))
                line.rig.git("remote", "set-url", "origin", origin)
                line.rig.git("pull", "-q", "origin", "main")
            line.member({f"{name}.txt": "x\n"})
            self.assertEqual(line.land().code, 0)
            return names.read_text().split()[-1]

        own = landed_from("acme")
        self.assertEqual(landed_from("borrowing", "--shared", str(checkout)), own)
        self.assertNotEqual(landed_from("plain", origin), own)
        shared = landed_from("borrowing-origin", "--shared", origin)
        origin = str(Line(files, home=line.home, name="gadget").rig.bare)
        self.assertNotEqual(landed_from("gadget", "--shared", origin), shared)

    def test_a_new_run_starts_beside_a_check_that_waits_here(self):
        # Owner, 30 Oct 2026: nothing waits for compute.  The test holds this host's one turn.
        line = Line({"t/a.sh": "true\n",
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        home = line.home
        akconfig.write(home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        home.env.pop("AK_MAX_RUNS")     # admission and heavy suite turns, which it turns off
        home.env.update(AK_HOST_READINGS=json.dumps({"cpus": 4, "load": 0, "free_mb": 400}),
                        AK_MIN_FREE_MB="0", AK_SLOT_POLL="0.5")
        home.fake("ssh", SSH.replace("load 0", "load 4").replace("room_mb 65536", "room_mb 0"))
        fakeadapter.install(home, claude="work", codex="pass")["claude"].behave(
            {"write": {"retry.txt": "hello\n"}, "commit": "add retry.txt", "hand_in": [["done"]]})
        line.member({"api.txt": "x\n"})

        def until(done, what):
            deadline = time.monotonic() + 240
            while not done():
                self.assertLess(time.monotonic(), deadline, what)
                time.sleep(0.2)

        with (home.path / ".agentkit" / "runs" / ".heavy-0.lock").open("a") as turn:
            fcntl.flock(turn, fcntl.LOCK_EX)
            lander = home.spawn("run", "--lander", line.line)
            until(lambda: "heavy suite turn" in home.log("spawn-1.out").read_text(),
                  "the line's check never waited here")
            task = taskfile.write(home, line.rig.path, "Add retry", name="retry")
            self.assertEqual(home.ak("run", str(task), "--bg", "--no-merge").code, 0)
            new = next(path for path in taskfile.runs(home) if path.name != "fix-1") / "run.json"
            until(lambda: json.loads(new.read_text())["state"] != "queued",
                  "the new run never left the queue")
            self.assertIsNone(lander.poll())


if __name__ == "__main__":
    unittest.main()
