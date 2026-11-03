"""A suite red in every piece reaches the next model bounded, however many pieces it ran in.

Each piece hands on its end and the pieces' number is the machines', so together they once made
a prompt no harness takes. Black-box, with scripted harnesses and a host with room for many pieces.
"""

import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

LOUD = "head -c 30000 /dev/zero | tr '\\0' x; exit 1  # AK_SHARD"
ROOM = {"cpus": 16, "load": 0, "free_mb": 128000, "slice_cpu_quota": 16, "slice_cpu_used": 0,
        "slice_memory_high_mb": 128000, "slice_memory_used_mb": 0}
WHOLE = re.compile(r"^\[only part of this output is shown; all of it is in (.+)\]$", re.M)


class ARedSuite(unittest.TestCase):
    def test_the_next_turn_gets_a_part_small_enough_and_the_name_of_the_whole(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude=fakeadapter.WORK, codex=fakeadapter.PASS)
            task = taskfile.write(home, Rig(home, "widgets").path, done_when=(LOUD,),
                                  front={"rounds": 2})
            home.ak("run", str(task), "--no-merge", timeout=300,
                    env={"AK_HOST_READINGS": json.dumps(ROOM)})
            prompts = taskfile.only_run(home).rglob("prompt.md")
            text = max((path.read_text() for path in prompts), key=len)
            self.assertLess(len(text), 300 * 1024)
            self.assertIn("AK_SHARD=1/", Path(WHOLE.search(text)[1]).read_text())


if __name__ == "__main__":
    unittest.main()
