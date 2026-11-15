"""A seat's kept price follows a rename that wins the record's lock after `keep_price` resolves
the seat, inside a pass too, and says why when the record goes instead."""

import contextlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, look, matrix, menu, quality


def row(harness, name, share, cost):
    """One board row an invented `acme-<name>-1` entry runs at `high`."""
    slug = f"acme-{name}-1"
    return {"release": slug, "name": f"Acme {name.title()} 1", "maker": "Acme", "effort": "high",
            "yours": [{"harness": harness, "model": slug}],
            "values": {quality.INTEL: 50, "aa.frontierCode20": share, "aa.terminalBench40": share,
                       "arena.agent": share, "aa.omniscience": share * 100,
                       "aa.automationBenchPartialScore": share,
                       **{key: cost for key in quality.COSTS.values()}}}


class KeepPriceRace(Sandbox):
    def setUp(self):
        super().setUp()
        entry = next(iter(self.cfg["models"].values()))
        harness = entry["harness"]
        self.cfg["models"] = {name: {**entry, "model": f"acme-{name}-1", "effort": "high"}
                              for name in ("base", "dear", "top")}
        self.cfg["defaults"] = {"orchestrator": "top", "workers": ["base"], "reviewers": ["top"]}
        config.save(self.cfg)
        lineup = [row(harness, "base", 0.84, 1), row(harness, "dear", 0.80, 2),
                  row(harness, "top", 0.90, 3)]
        self.answer = matrix.answer(lineup, cfg=self.cfg, task_usage=({}, {}))

    def taken(self, worker="top", price=None):
        """`acme-fix` saved on `base`, then moved onto `worker`, returning `(before, selected)`."""
        config.save_session(self.cfg, "acme-fix", "top", ["base"],
                            {"reviewers": ["top"],
                             **({"executor_price": price} if price is not None else {})})
        before = matrix.uses(self.cfg, config.load_session(self.cfg, "acme-fix"),
                             self.answer)["execute"][2]
        config.update_session("acme-fix", workers=[worker])
        return before, config.load_session(self.cfg, "acme-fix")

    def test_a_rename_during_the_price_write_keeps_or_removes_it_where_the_seat_went(self):
        original_lock = config._record_lock
        # A single move inside a pass that cached the old record, and a move there and back.
        for moves in ([("acme-fix", "acme-move")],
                      [("acme-fix", "acme-move"), ("acme-move", "acme-fix")]):
            with self.subTest(moves=moves):
                for name in ("acme-fix", "acme-move"):
                    config.session_path(name).unlink(missing_ok=True)
                before, selected = self.taken("top")
                steps = iter(moves)
                in_hook = False

                @contextlib.contextmanager
                def rename_before_lock(path, steps=steps):
                    nonlocal in_hook
                    if not in_hook:
                        step = next(steps, None)
                        if step and path == config.session_path(step[0]):
                            in_hook = True
                            try:
                                config.rename_session(*step)
                            finally:
                                in_hook = False
                    with original_lock(path):
                        yield

                with look.one_look():
                    config.session_records()        # caches `acme-fix` before the rename
                    with patch.object(config, "_record_lock", rename_before_lock):
                        note = menu.keep_price(self.cfg, "acme-fix", selected, self.answer,
                                               "execute", before)
                self.assertEqual(note, "")
                landed = moves[-1][1]
                record = json.loads(config.session_path(landed).read_text())
                self.assertEqual(record["workers"], ["top"])
                self.assertEqual(record["executor_price"],
                                 {"limit": None, "cost_unit": "board_dollars", "model": "top",
                                  "effort": "high"})

        # Removing a kept price onto a beaten row across a rename removes it where the seat went.
        for name in ("acme-fix", "acme-move"):
            config.session_path(name).unlink(missing_ok=True)
        before, selected = self.taken("dear", price={"limit": 2, "cost_unit": "board_dollars",
                                                     "model": "base", "effort": "high"})
        moved = False

        @contextlib.contextmanager
        def rename_once(path):
            nonlocal moved
            if path == config.session_path("acme-fix") and not moved:
                moved = True
                config.rename_session("acme-fix", "acme-move")
            with original_lock(path):
                yield

        with patch.object(config, "_record_lock", rename_once):
            self.assertEqual(
                menu.keep_price(self.cfg, "acme-fix", selected, self.answer, "execute", before), "")
        record = json.loads(config.session_path("acme-move").read_text())
        self.assertEqual(record["workers"], ["dear"])
        self.assertNotIn("executor_price", record)

    def test_a_record_removed_during_the_price_write_says_why_under_the_rows(self):
        original_lock = config._record_lock
        for rename_first in (False, True):
            with self.subTest(rename_first=rename_first):
                for name in ("acme-fix", "acme-move"):
                    config.session_path(name).unlink(missing_ok=True)
                before, selected = self.taken("top")
                step = 0
                in_hook = False

                @contextlib.contextmanager
                def remove_before_lock(path, rename_first=rename_first):
                    nonlocal step, in_hook
                    if not in_hook and step == 0 and path == config.session_path("acme-fix"):
                        step = 1
                        in_hook = True
                        try:
                            if rename_first:
                                config.rename_session("acme-fix", "acme-move")
                            else:
                                path.unlink()
                        finally:
                            in_hook = False
                    elif not in_hook and step == 1 and path == config.session_path("acme-move"):
                        step = 2
                        path.unlink()
                    with original_lock(path):
                        yield

                with patch.object(config, "_record_lock", remove_before_lock):
                    note = menu.keep_price(self.cfg, "acme-fix", selected, self.answer,
                                           "execute", before)
                self.assertEqual(note, "session: acme-fix has no saved models")


if __name__ == "__main__":
    unittest.main()
