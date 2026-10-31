"""A pass looks at the runs once (`record.one_look`): every ask on its thread gets what the first
saw, while another thread, as the main one beside the screen's watcher, and the next pass look
again."""

import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, record


def write(name):
    (config.RUNS / name).mkdir(parents=True)
    (config.RUNS / name / "run.json").write_text(json.dumps({"run_id": name, "state": "pass"}))


def names(runs):
    return [directory.name for directory, _ in runs]


class APassLooksAtTheRunsOnce(Sandbox):
    def test_a_pass_hands_its_thread_the_first_look_and_the_next_pass_looks_again(self):
        write("fix-api")
        with record.one_look():
            first = record.runs()
            write("fix-cli")
            with record.one_look():
                self.assertIs(record.runs(), first)
            beside = []
            reader = threading.Thread(target=lambda: beside.extend(record.runs()))
            reader.start()
            reader.join()
            self.assertEqual(names(beside), ["fix-api", "fix-cli"])
            self.assertEqual(names(record.runs()), ["fix-api"])
        self.assertEqual(names(record.runs()), ["fix-api", "fix-cli"])


if __name__ == "__main__":
    unittest.main()
