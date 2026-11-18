"""An ending reads model policy once, and only when its review decides it: a provider edited
between two reads made `PASS merged` carry no PR, and a FAIL give a passing run's reason, and a
config that will not load must leave what a blocked, failed or unneeded run's record says, and
what a passing one says, whatever the file's fault.  Each of the three that tell an ending, in process; a seat's look, the one of them `ak` reaches alone,
is tests/test_key_an_ending_reads_one_config.py.

Offline: a temporary HOME (`Sandbox`) whose `config.load` is patched.
"""

import copy
from itertools import chain, repeat
import os
import sys
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, handback, record

TOLD = (("handback_line", lambda directory, state: handback.handback_line(state, directory, save=False)),
        ("decision_line", lambda directory, state:
            handback.decision_line(state, directory, save=False, report=True)),
        ("result_opening", lambda directory, state: handback.result_opening(directory, state)))


class EndingReadsConfigOnce(Sandbox):
    def ending(self, name, **extra):
        directory = self.ended(name, repo=str(self.root), **extra)
        state = record.read_state(directory)
        state["review"].update(head_sha="b" * 40, tree_sha="c" * 40)    # what a repo's PASS holds
        return directory, state

    def test_an_edit_after_the_first_read_changes_nothing_the_ending_says(self):
        edited = copy.deepcopy(self.cfg)
        edited["models"]["astra"]["provider"] = config.model(self.cfg, "opus")["provider"]
        merged = self.ending("acme-merged", merged=True, pr="https://github.com/acme/widget/pull/1")
        unmerged = self.ending("acme-unmerged")
        for (name, said), (directory, state) in zip(TOLD, (merged, unmerged, merged)):
            with patch.object(config, "load", return_value=self.cfg):
                first = said(directory, state)
            with patch.object(config, "load", return_value=edited):
                self.assertNotEqual(said(directory, state), first, name)    # the edit matters
            with patch.object(config, "load", side_effect=chain([self.cfg], repeat(edited))):
                self.assertEqual(said(directory, state), first, name)

    def test_an_ending_its_record_decides_reads_no_config(self):
        why = "Saved diagnostic."
        for outcome in ("blocked", "error", "not_needed"):
            directory, state = self.ending(f"acme-{outcome}", state=outcome, error=why, not_needed=why)
            with patch.object(config, "load", side_effect=ValueError("config.toml will not load")):
                for name, said in TOLD:
                    told = said(directory, state)
                    if not (name == "decision_line" and outcome == "not_needed"):   # nothing to decide
                        self.assertIn(why, told, f"{name} of {outcome}")

    def test_a_file_tomllib_cannot_read_leaves_what_the_record_says(self):
        # past Python's digit limit tomllib raises a bare ValueError, no TOMLDecodeError
        self.addCleanup(sys.set_int_max_str_digits, sys.get_int_max_str_digits())
        sys.set_int_max_str_digits(4300)
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        told = ((self.ending("acme-checks", merged=True, checks_only=True, reviewer=None,
                             review={"executor": "opus", "verdict": "PASS", "returncode": 0,
                                     "done_when": True, "no_review": True}), "# PASS, merged"),
                (self.ending("acme-reviewed", error="Saved diagnostic."), "Why: Saved diagnostic"))
        broken = {config.HOME / config.CONFIG_NAME: b"max_runs = " + b"9" * 4301 + b"\n",
                  adapters / "acme.toml": b'name = "\xff"\n'}
        for path, data in broken.items():
            path.write_bytes(data)
            for (directory, state), words in told:
                with self.subTest(path.name, record=directory.name):
                    self.assertIn(words, handback.result_opening(directory, state))
            path.unlink()


if __name__ == "__main__":
    unittest.main()
