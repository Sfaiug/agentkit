"""An ending reads model policy once: a provider edited between two reads made `PASS merged`
carry no PR, and a FAIL give a passing run's reason.  Each of the three that tell an ending, in
process; a seat's look, the one of them `ak` reaches alone, is tests/test_key_an_ending_reads_one_config.py.

Offline: a temporary HOME (`Sandbox`); `config.load` returns the edited file after its first read.
"""

import copy
from itertools import chain, repeat
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, handback, record


class EndingReadsConfigOnce(Sandbox):
    def test_an_edit_after_the_first_read_changes_nothing_the_ending_says(self):
        edited = copy.deepcopy(self.cfg)
        edited["models"]["astra"]["provider"] = config.model(self.cfg, "opus")["provider"]
        merged = self.ended("acme-merged", merged=True, pr="https://github.com/acme/widget/pull/1",
                            repo=str(self.root))
        unmerged = self.ended("acme-unmerged", repo=str(self.root))
        endings = (
            ("handback_line", merged, lambda directory, state, cfg:
                handback.handback_line(state, directory, cfg, save=False)),
            ("decision_line", unmerged, lambda directory, state, cfg:
                handback.decision_line(state, directory, cfg, save=False, report=True)),
            ("result_opening", merged, lambda directory, state, cfg:
                handback.result_opening(directory, state, cfg)))
        for name, directory, said in endings:
            state = record.read_state(directory)
            state["review"].update(head_sha="b" * 40, tree_sha="c" * 40)    # what a repo's PASS holds
            first = said(directory, state, self.cfg)
            self.assertNotEqual(said(directory, state, edited), first, name)    # the edit matters
            with patch.object(config, "load", side_effect=chain([self.cfg], repeat(edited))):
                self.assertEqual(said(directory, state, None), first, name)


if __name__ == "__main__":
    unittest.main()
