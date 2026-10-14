"""A session whose record names a model the config no longer has stays usable.

Models are renamed and removed while seats built on them are still open. Reading such a
seat's record passes over the gone model -- in memory, the way `load` passes over one in
[defaults], with the first remaining model taking a place it empties -- instead of
refusing the record whole, which hid the seat's roles on `c`, stopped it launching runs
and stopped it resuming. The orchestrator's name is kept as recorded: an open seat is
still running it, and picking another on `c` moves the seat. Saving a new session still
refuses a model the config has not got, and a model entry that is there but broken
still says so.

Offline: session records in a throwaway HOME, the config's models taken out in memory.
"""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import config, menu


class RemovedModel(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))

    def save(self, name="fix-api", orchestrator="opus", workers=("opus", "astra"),
             reviewers=("astra",)):
        extra = {"cwd": str(self.root), "created": 100}
        if reviewers is not None:
            extra["reviewers"] = list(reviewers)
        return config.save_session(self.cfg, name, orchestrator, list(workers), extra)

    def first_left(self):
        return config.offered(self.cfg)[0]

    def test_a_removed_worker_and_reviewer_are_passed_over_and_the_file_is_left_as_it_was(self):
        self.save(workers=("opus", "astra"), reviewers=("astra", "opus"))
        config.remove_model(self.cfg, "astra")
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual(record["orchestrator"], "opus")
        self.assertEqual(record["workers"], ["opus"])
        self.assertEqual(record["reviewers"], ["opus"])
        on_disk = json.loads(config.session_path("fix-api").read_text())
        self.assertEqual(on_disk["workers"], ["opus", "astra"])   # the passing over is in memory
        self.assertEqual(on_disk["reviewers"], ["astra", "opus"])

    def test_the_first_remaining_model_takes_an_emptied_place(self):
        self.save(name="solo", workers=("astra",), reviewers=("astra",))
        config.remove_model(self.cfg, "astra")
        record = config.load_session(self.cfg, "solo")
        self.assertEqual(record["workers"], [self.first_left()])
        self.assertEqual(record["reviewers"], [self.first_left()])

    def test_a_legacy_record_whose_only_worker_went_still_loads(self):
        self.save(name="old", workers=("astra",), reviewers=None)
        config.remove_model(self.cfg, "astra")
        record = config.load_session(self.cfg, "old")
        self.assertEqual(record["workers"], [self.first_left()])
        self.assertNotIn("reviewers", record)

    def test_executors_left_empty_stay_empty(self):
        self.save(name="builds", workers=(), reviewers=("astra", "opus"))
        config.remove_model(self.cfg, "astra")
        record = config.load_session(self.cfg, "builds")
        self.assertEqual(record["workers"], [])
        self.assertEqual(record["reviewers"], ["opus"])

    def test_a_removed_orchestrator_keeps_its_name_and_the_seat_still_reads_its_groups(self):
        self.save()
        config.remove_model(self.cfg, "opus")
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}):
            active = config.active_session(self.cfg)     # what `ak run` in the seat reads first
            self.assertEqual(active["orchestrator"], "opus")   # the open seat is running it
            self.assertEqual(config.workers(self.cfg), ["astra"])
            self.assertEqual(config.reviewers(self.cfg), ["astra"])

    def test_the_next_flip_on_c_saves_the_record_without_the_gone_model(self):
        self.save()
        config.remove_model(self.cfg, "astra")
        record = config.load_session(self.cfg, "fix-api")
        selected = {"orchestrator": record["orchestrator"], "workers": list(record["workers"]),
                    "reviewers": list(record["reviewers"])}
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "fable", 1, {}), "")
        on_disk = json.loads(config.session_path("fix-api").read_text())
        self.assertEqual(on_disk["workers"], ["opus", "fable"])
        self.assertEqual(on_disk["reviewers"], [self.first_left()])

    def test_saving_a_new_session_still_refuses_a_model_the_config_has_not_got(self):
        config.remove_model(self.cfg, "astra")
        with self.assertRaisesRegex(config.Error, "unknown model 'astra'"):
            self.save(name="new")
        self.assertFalse(config.session_path("new").exists())

    def test_a_broken_model_entry_still_says_so(self):
        self.save()
        del self.cfg["models"]["opus"]["effort"]
        with self.assertRaisesRegex(config.Error, "missing 'effort'"):
            config.load_session(self.cfg, "fix-api")


if __name__ == "__main__":
    unittest.main()
