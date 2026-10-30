"""A tick asks about a merged run's seat from the one read of every run its pass already made: a
read each was 5167 files read 200 times a tick, a quarter of its 8 minutes (30 Oct 2026)."""

from collections import Counter
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, record, watch


class ATickReadsEachRunOnce(Sandbox):
    def reads_of_a_bystander(self):
        reads, real = Counter(), record.read_state
        def counted(directory, *args, **kw):
            reads[directory.name] += 1
            return real(directory, *args, **kw)
        with patch.object(record, "read_state", counted), \
                patch.object(watch, "after_merge_status", return_value=("passed", None, None)):
            watch.after_merge_checks({}, False, lambda _: None, now=10000)
        return reads["bystander"]

    def test_the_pass_over_merges_reads_a_run_of_nobodys_no_more_for_each_merged_run(self):
        config.save_session(self.cfg, "fix-api", "opus", ["astra"], {"cwd": str(self.root)})
        config.plan_path("fix-api").write_text("- [ ] the parser is live\n")
        self.ended("bystander", handed_back=9991, reported=True)
        alone = self.reads_of_a_bystander()
        self.ended("waits", owner="fix-api", state="queued", slot_waiting=True)   # so all three ride
        for name in ("run-a", "run-b", "run-c"):
            self.ended(name, owner="fix-api", merged=True, live_at=9995, merge_sha="a" * 40,
                       pr="https://github.com/acme/widget/pull/7", handed_back=9991, reported=True)
        self.assertEqual(self.reads_of_a_bystander(), alone)


if __name__ == "__main__":
    unittest.main()
