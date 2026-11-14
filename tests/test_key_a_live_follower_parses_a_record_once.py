"""A project's live follower parses a run's record once while it does not change, the asks after a
deferred line of its seat's plan included.

On 13 Nov 2026 a host held 6,464 run records, 122 MB, and a seat in a long turn owed two deferred
lines with a merge of its own live: at each ask the merge's follower parsed every record again
for whether a run had those lines, a whole core for as long as the notice was owed.  Black-box:
AK_BIN on the Home, project, seat and merge of `test_key_merges_going_live_share_one_follower`,
the Home also holding older runs' records, ended and padded to tens of megabytes together, and
the seat's plan a deferred line of the project that no run has.  The seat works, never at its
prompt, so the merge goes live with its notice owed and the follower goes on asking: over two
intervals after the ask that took it live, what it reads (`rchar`) grows by less than those
records weigh.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_live_follower_reads_the_records_once import INTERVAL
from test_key_merges_going_live_share_one_follower import FollowedMerges, following

OLDER, PAD = 32, 1 << 20    # older runs' records, and the summary padding each


def read(pid):
    """What the process has read so far, in bytes, by the kernel's count."""
    io = Path(f"/proc/{pid}/io").read_text()
    return int(next(line for line in io.splitlines() if line.startswith("rchar:")).split()[1])


class LiveFollowerParsesARecordOnce(FollowedMerges):
    def setUp(self):
        super().setUp()
        self.seat.show("claude-working-pane.txt")
        api = self.rigs["api"]
        root = api.git("rev-list", "--max-parents=0", "HEAD")
        self.home.write(f".agentkit/state/plan-{self.seat.name}.md",
                        f"- [ ] Fix app.py:1 · check: `false` · {api.path}#{root} · deferred"
                        " · written 2026-11-13 09:00\n")
        self.weight = 0
        for n in range(OLDER):
            run_id = f"20261101-1200-api-old-{n}"
            self.weight += self.home.write(f".agentkit/runs/{run_id}/run.json", {
                "run_id": run_id, "state": "stopped", "repo": str(api.path),
                "finished_at": time.time() - 12 * 86400,
                "round_summaries": [{"round": 1, "verdict": "FAIL", "summary": "x" * PAD}],
            }).stat().st_size

    def test_a_follower_asking_after_a_deferred_line_reads_no_unchanged_record_again(self):
        directory = self.merge("api", "one")
        self.home.write("live-ok", "")
        self.until(lambda: json.loads((directory / "run.json").read_text()).get("live_at"),
                   "took the run live")
        (pid,) = following(self.home)
        time.sleep(INTERVAL)    # past the ask that took it live, which parses each a first time
        before = read(pid)
        time.sleep(2 * INTERVAL)
        # still following, its notice still owed: the count spans its asks
        self.assertEqual(following(self.home), {pid: "api"})
        self.assertFalse([line for line in self.seat.lines() if "is live" in line])
        self.assertLess(read(pid) - before, self.weight)


if __name__ == "__main__":
    unittest.main()
