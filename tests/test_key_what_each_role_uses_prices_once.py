"""What each role uses (matrix.uses), as the models screen and `ak models` say it, orders a
seat's marks off the answer it is given: a role's task is priced (spend.roles, every login's
week read) once for the answer, never again for each role.  Pricing it four times as the screen
opened and four more as the boards landed held its keys for 28 seconds on 7 Nov 2026."""

import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import matrix, spend


class WhatEachRoleUsesPricesOnce(Sandbox):
    def test_what_each_role_uses_reads_the_answer_it_is_given(self):
        matrix.cache_path().write_text('{"matrix": {"lineup": []}}')     # a lineup is stored
        priced = []
        with patch.object(spend, "roles", lambda cfg: priced.append(cfg) or {}):
            found = matrix.answer([], cfg=self.cfg)
            matrix.uses(self.cfg, self.cfg["defaults"], found)
        self.assertEqual(len(priced), 1)


if __name__ == "__main__":
    unittest.main()
