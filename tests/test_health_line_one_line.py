"""A live-health failure reaches its seat as one entered line, its probe's output whole.

Offline: a temporary HOME, and the deadline branch of `after_merge_health` read as a dry run.
"""

import unittest

from fixtures.sandbox import Sandbox
from agentkit import watch

PR = "https://github.com/acme/widget/pull/7"


class HealthLineOneLine(Sandbox):
    def line(self, output):
        state = {"finished_at": 0, "repo": "/nowhere",
                 "health": {"command": "probe", "output": output}}
        verdict, check, url = watch.after_merge_health(
            None, state, "acme/widget", "a" * 40, PR, watch.AFTER_MERGE_WINDOW + 1,
            True, lambda _line: None, {})
        self.assertEqual(verdict, "failed")
        return watch.after_merge_line(check, "main", url)

    def test_output_lines_become_separators_and_nothing_is_cut(self):
        line = self.line("GET /health 502\n\nupstream down\nretry later")
        self.assertEqual(line, f"health: probe failed on main after this merge. {PR}; "
                               "GET /health 502; upstream down; retry later. Fix the target.")

    def test_one_line_of_output_reads_as_before(self):
        self.assertEqual(self.line("GET /health 502"),
                         f"health: probe failed on main after this merge. {PR}; "
                         "GET /health 502. Fix the target.")


if __name__ == "__main__":
    unittest.main()
