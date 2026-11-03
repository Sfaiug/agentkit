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
# Red once in each piece, on 20 lines a re-run does not print: a marker in the tree outlives the go.
ONCE = ('m=.seen-${AK_SHARD%/*}; [ -e "$m" ] && exit 0; : > "$m"; '
        "for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do "
        "printf 'detail %s ' $n; head -c 3000 /dev/zero | tr '\\0' x; echo; done; "
        "exit 1  # AK_SHARD")
ROOM = {"cpus": 16, "load": 0, "free_mb": 128000, "slice_cpu_quota": 16, "slice_cpu_used": 0,
        "slice_memory_high_mb": 128000, "slice_memory_used_mb": 0}
WHOLE = re.compile(r"^\[only part of this output is shown; all of it is in (.+)\]$", re.M)


def longest_prompt(home):
    return max(len(path.read_text()) for path in taskfile.only_run(home).rglob("prompt.md"))


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

    def test_every_piece_that_failed_then_passed_keeps_its_follow_up(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude=fakeadapter.WORK, codex=fakeadapter.PASS)
            task = taskfile.write(home, Rig(home, "widgets").path, done_when=(ONCE,),
                                  front={"rounds": 2})
            home.ak("run", str(task), "--no-merge", timeout=300,
                    env={"AK_HOST_READINGS": json.dumps(ROOM)})
            followups = json.loads((taskfile.only_run(home) / "run.json").read_text())["followups"]
            pieces = int(re.search(r"AK_SHARD=\d+/(\d+)", followups[0])[1])
            self.assertEqual(len(followups), pieces)
            self.assertGreater(pieces, 4)       # more than fit with their details
            self.assertTrue(all("detail 20 " in record for record in followups))
            self.assertLess(longest_prompt(home), 300 * 1024)

    def test_a_red_piece_stays_in_view_past_the_pieces_that_flaked(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude=fakeadapter.WORK, codex=fakeadapter.PASS)
            red = f'[ "${{AK_SHARD%/*}}" = 1 ] && exit 1; {ONCE}'
            task = taskfile.write(home, Rig(home, "widgets").path, done_when=(red,),
                                  front={"rounds": 2})
            home.ak("run", str(task), "--no-merge", timeout=300,
                    env={"AK_HOST_READINGS": json.dumps(ROOM)})
            prompts = [path.read_text() for path in taskfile.only_run(home).rglob("prompt.md")]
            flaked = [text for text in prompts if re.search(r"^flaky: ", text, re.M)]
            self.assertTrue(flaked)
            self.assertTrue(all("--- AK_SHARD=1/" in text for text in flaked))
            self.assertLess(longest_prompt(home), 300 * 1024)


if __name__ == "__main__":
    unittest.main()
