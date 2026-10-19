"""Every plan line has a check: `ak plan add --eye` and `ak plan tick` are gone, so no seat waits
on the owner to confirm what it built.  How a change looks is the owner's to judge once it is
live.  An eye line a plan still holds from before reads done, open or ticked, wherever ak counts
a plan: the stop hook, the done and the menu's bar.

Offline: a throwaway HOME and a plan file written by hand.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, plan, stop, watch


class EveryLineHasACheck(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {config.SESSION_ENV: "fix-api"}))
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})

    def test_an_eye_line_can_no_longer_be_added_or_ticked(self):
        for argv in (["add", "the hero looks calm", "--eye"], ["tick", "1"]):
            with self.subTest(argv=argv), self.assertRaisesRegex(config.Error, "usage: ak plan"):
                plan.main(argv)
        self.assertNotIn("--eye", (REPO / "orchestrator.md").read_text())
        self.assertNotIn("ak plan tick", (REPO / "orchestrator.md").read_text())

    def test_an_eye_line_from_before_reads_done_open_or_ticked(self):
        eye = "the hero looks calm · your eye · acme · written 2026-10-01 10:00"
        config.plan_path("fix-api").write_text(
            f"- [ ] {eye}\n"
            f"- [x] {eye} · done your yes 2026-10-01 11:00\n"
            f"- [x] {eye}\n")
        self.assertEqual([plan.is_open(line) for line in plan.lines("fix-api")], [False] * 3)
        self.assertIsNone(stop.owed_line("fix-api"))
        self.assertEqual(plan.require_done("fix-api"), set())
        self.assertEqual(watch.plan_progress("fix-api"), (3, 3))

    def test_the_bar_counts_done_as_the_stop_hook_does(self):
        config.plan_path("fix-api").write_text(
            "- [x] the API answers · check: `test -f api.txt` · acme · written 2026-10-01 10:00\n"
            "- [x] the docs say so\n"
            "- [ ] the export works\n")
        # a check line ticked by hand, with no commit its check passed on, proves nothing
        self.assertEqual(stop.owed_line("fix-api"), "the API answers")
        self.assertEqual(watch.plan_progress("fix-api"), (1, 3))


if __name__ == "__main__":
    unittest.main()
