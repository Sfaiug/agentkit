"""The run first in line for a slot half an hour while the queue is polled is a stall for the
`audit` seat, one per wait.  Offline: temporary runs and state directories and the clock
injected."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, land, record, stuck

NOW = 1_800_000_000.0
API, WEB = "20270115-0900-fix-api", "20270115-0901-fix-web"


class FirstInLineHalfAnHour(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-first-in-line-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        for name in ("RUNS", "STATE"):
            (Path(tmp.name) / name.lower()).mkdir()
        for patcher in (patch.object(config, "RUNS", Path(tmp.name) / "runs"),
                        patch.object(config, "STATE", Path(tmp.name) / "state"),
                        patch.object(config, "ensure_dirs"),
                        patch.object(config, "audit", return_value={"on": True}),
                        patch.object(gate, "SLOT_POLL", 30),
                        patch.object(gate, "time", SimpleNamespace(time=lambda: self.clock))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def polls(self, by, queue, start, end):
        """The queue `by`'s polls leave each half minute, but those it skips behind the first."""
        for self.clock in [*range(int(start), int(end), 30), end]:
            if not gate.behind_first(by):
                gate._save_queue(0, queue)

    def found(self, now):
        return [key for key, _what, line in stuck.stalls(now) if line]

    def told(self, now):
        """The stall the tick's scan tells at `now`, delivered at once."""
        found = stuck.scan({}, lambda _: None, now)
        if found:
            stuck.write({**found[1], "delivered": now})
            return found[1]["told"][-1]

    def test_a_run_first_in_line_half_an_hour_is_one_stall_per_wait(self):
        self.polls(API, [API, WEB], NOW - 3000, NOW)
        self.assertEqual(list(stuck.stalls(NOW)), [(
            f"slot:{API}:{NOW - 3000}", "the stall of the slot queue",
            f"ak stalled: {API} has been first in line for a slot for 50m, more than 30m, with 1 "
            "behind it; `ak run status` shows what it waits on. Find why and build the smallest "
            "change to ak that keeps it from happening again, through the line.")])
        self.assertEqual(self.found(NOW - 1), [f"slot:{API}:{NOW - 3000}"])  # polled after `now`
        self.assertEqual(self.found(NOW + 150), [])     # four polls missed: nobody polls it
        self.polls(API, [API, WEB], NOW + 180, NOW + 1970)     # and a new wait starts
        self.assertEqual(self.found(NOW + 1970), [])
        self.polls(API, [API, WEB], NOW + 2000, NOW + 2000)
        self.assertEqual(self.found(NOW + 2000), [f"slot:{API}:{NOW + 180}"])
        self.polls(API, [WEB], NOW + 2030, NOW + 2030)     # let in, it hands first place on
        self.assertEqual(self.found(NOW + 2040), [])

    def test_a_wait_told_stays_told_while_the_clock_is_set_back(self):
        self.polls(API, [API, WEB], NOW - 1830, NOW)
        self.assertEqual(self.told(NOW), f"slot:{API}:{NOW - 1830}")
        self.polls(API, [API, WEB], NOW - 90, NOW - 90)     # back under half an hour
        land._keep_passes(config.RUNS / ".merge-acme.lock", {     # and another stall is told
            "started": NOW - 3090, "took": [600, 700, 800], **record.process_owner()})
        self.assertEqual(self.told(NOW - 90), f".merge-acme.lock:{NOW - 3090}")
        self.polls(API, [API, WEB], NOW - 60, NOW + 30)
        self.assertIsNone(self.told(NOW + 30))

    def test_a_first_that_never_polls_is_a_stall_the_run_behind_it_finds(self):
        self.polls(WEB, [API, WEB], NOW - 3000, NOW)
        self.assertEqual(self.found(NOW), [f"slot:{API}:{NOW - 3000}"])


if __name__ == "__main__":
    unittest.main()
