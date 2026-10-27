"""A board's model is never found by a shorter name of another version; `prepare` fakes the
boards and harnesses the matrix's tests read.

Offline: the boards' answers are handed in as bytes (tests/test_model_matrix.py's), the harness
manifests, catalogs and the installed harnesses are faked, and a throwaway HOME holds the
cache.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import boards, config, matrix, terminal
import test_model_matrix as boards_test

CATALOGS = {"claude": [{"id": "claude-opus-5-5", "efforts": ["low", "medium", "high", "xhigh", "max"]},
                       {"id": "claude-haiku-4-5", "efforts": ["none"]},
                       {"id": "claude-opus-4-7", "efforts": []}],
            "codex": [{"id": "gpt-6-astra", "efforts": ["low", "medium", "high", "xhigh", "max"]}],
            "muse": [{"id": "muse-wonder-full-1.0", "efforts": ["low", "high", "xhigh", "max"]},
                     {"id": "muse-spark-1.3-contributor", "efforts": ["low", "xhigh"]}]}


def prepare(case):
    """The boards answered by bytes, the harness manifests, catalogs and installed harnesses
    faked, and a configured Muse Wonder Full, on a Sandbox case."""
    case.boards = boards_test.Boards()
    boards_test.AA += [
        {"name": "Muse Wonder Full (max)", "terminalBench40": 0.57},
        {"name": "Muse Spark 1.3 (xhigh)", "terminalBench40": 0.4}]
    case.addCleanup(lambda: boards_test.AA.__delitem__(slice(-2, None)))
    case.stack.enter_context(patch.object(boards_test, "TABLE", boards_test.TABLE
                                          + "muse-spark-1.3-contributor,50.0,\n"))
    case.stack.enter_context(patch.object(boards, "fetch_bytes", case.boards))
    # acme has a manifest and no binary here: none of its models gets a row
    case.stack.enter_context(patch.object(config, "manifests", return_value=[
        (harness, {}) for harness in (*CATALOGS, "acme")]))
    case.stack.enter_context(patch.object(config, "harness_present",
                                          side_effect=lambda harness: harness in CATALOGS))
    case.stack.enter_context(patch.object(config, "catalog",
                                          side_effect=lambda harness, cfg=None: CATALOGS[harness]))
    case.stack.enter_context(patch.object(terminal, "width", return_value=100))
    case.cfg["models"]["wonder"] = {"harness": "muse", "model": "muse-wonder-full-1.0",
                                    "effort": "max", "provider": "meta"}


class ModelRows(unittest.TestCase):
    def test_a_shorter_board_name_never_stands_for_a_longer_id_of_another_version(self):
        index = {"claudesonnet5": [{"model": "Claude Sonnet 5", "effort": None, "values": {}}],
                 "claudesonnet55": [{"model": "Claude Sonnet 5.5", "effort": None, "values": {}}]}
        self.assertEqual(matrix.found(index, "claude-sonnet-5-5")[0]["model"], "Claude Sonnet 5.5")
        self.assertEqual(matrix.found({"claudesonnet5": index["claudesonnet5"]},
                                      "claude-sonnet-5-5"), [])


if __name__ == "__main__":
    unittest.main()
