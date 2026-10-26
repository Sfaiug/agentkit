"""Every line ak types into a seat fits its composer whole (`watch.too_long`).

24 Oct 2026: a failed harness gate's 2,075-character hand-back, raw screen dumps and all, was
folded by Claude into `[Pasted text #N]` and sat unsent for two days.  A hand-back names each
failed check by its `FAIL` line alone, whole or counted as left out, and points at the file
holding the rest; `type_at_prompt` types no line past the bound.

Offline: a temporary HOME (`Sandbox`), its default config's Claude bound, fake tmux.
"""

import re
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch, update, watch

COMMIT = "abcdef0123456789" * 2 + "abcdef01"
SEAT = "fix-api"


def smoke_log(count):
    """A smoke log as the 24 Oct one: each `FAIL` line with a screen dump printed under it."""
    titles = [f"FAIL  {n}f naming, exit and resume of the acme seat number {n}" for n in range(count)]
    dump = [f"      │ ❯ acme row {row} " + "─" * 60 + " │" for row in range(24)]
    lines = [f"PASS  {n} acme check" for n in range(30)]
    for title in titles:
        lines += [title, *dump]
    return titles, "\n".join([*lines, "smoke: 30 passed, %d failed" % count, "[exit 1]"]) + "\n"


class TypedLineFitsComposer(Sandbox):
    def assertFits(self, line, titles, path):
        self.assertIsNone(watch.too_long(line))
        self.assertTrue(config.tilde(path).startswith("~/"))  # as short however deep HOME is
        self.assertIn(config.tilde(path), line)
        self.assertNotIn("acme row", line)
        named = [title for title in titles if title in line]
        left = len(titles) - len(named)
        self.assertEqual(named, titles[:len(named)])
        if left:
            self.assertIn(f"{left} more failed checks left out", line)
        else:
            self.assertNotIn("left out", line)
        return named

    def test_a_harness_gate_failing_twice_hands_back_titles_and_its_log(self):
        self.assertEqual(watch.longest(), watch.screen("claude")["folds_over"])
        for count in (0, 2, 40):
            with self.subTest(failed=count):
                titles, log = smoke_log(count)
                path = config.TMP / f"update-{count}.log"
                path.write_text(log)
                plan = [{"name": f"acme{count}"}]
                for _ in range(2):
                    update.harness_gate_result(plan, False, "live", path)
                line = update._handed(config.STATE / update.HARNESS_GATES / f"acme{count}")["line"]
                self.assertIn(f"acme{count} harness upgrade", line)
                named = self.assertFits(line, titles, path)
                self.assertEqual(len(named) == count, count < 40)

    def test_tests_live_sh_failures_hand_back_titles_and_its_output(self):
        for standing in (False, True):
            for count, code in ((0, 1), (2, 1), (40, 1), (6, None)):
                with self.subTest(standing=standing, failed=count, code=code):
                    titles, log = smoke_log(count)
                    check = config.STATE / update.LIVE / f"{COMMIT}-{count}-{standing}-{code}"
                    check.mkdir(parents=True)
                    output = check / ("output" if code is not None else "output.tmp")
                    output.write_text(log)
                    (check / "failed").write_text("".join(f"{n}f\n" for n in range(count)))
                    said = []
                    update.live_hand_back(COMMIT, check, code, said.append, hand=False,
                                          standing=standing)
                    line = update._handed(check)["line"]
                    self.assertIn("standing faults" if standing else "failed on agentkit's main",
                                  line)
                    if standing:    # the faults go in label order: 0f, 1f, 10f, ...
                        titles.sort(key=lambda title: title.split()[1])
                    self.assertFits(line, titles, output)
                    self.assertEqual("stopped before it finished" in line, code is None)
                    self.assertTrue(said[0].startswith("WARN "))

    def test_a_line_past_the_bound_sends_no_keys(self):
        calls, said = [], []
        line = "run acme finished FAIL: " + "acme-finding " * 80

        def tmux(*args, **_kw):
            calls.append(args)
            return 0, ""

        with patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(watch, "pane_text", return_value="❯ \n"), \
                patch.object(watch, "_editor_kept", return_value={}):
            self.assertIsNotNone(watch.too_long(line))
            self.assertFalse(watch.type_at_prompt({"name": SEAT}, line, said.append, cfg=self.cfg))
        self.assertEqual([args for args in calls if args[0] == "send-keys"], [])
        self.assertEqual(len(said), 1)
        self.assertTrue(re.match(r"WARN run acme finished FAIL: acme-finding .*fix-api", said[0]))


if __name__ == "__main__":
    unittest.main()
