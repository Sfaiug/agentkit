"""In a seat, `ak run status` says it lists only that seat's runs and where every seat's are,
so an empty answer never reads as an idle host; offline."""

from contextlib import redirect_stdout
import io
import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, status


class StatusNamesItsSeat(Sandbox):
    def setUp(self):
        super().setUp()
        self.ended("20261023-0900-fix-api-timeout", owner="fix-api")

    def listing(self, seat=None):
        out = io.StringIO()
        with patch.dict(os.environ, {config.SESSION_ENV: seat} if seat else {}), \
                redirect_stdout(out):
            self.assertEqual(status.cmd_status([]), 0)
        return out.getvalue()

    def test_a_seat_without_runs_says_so_while_another_has_some(self):
        shown = self.listing(seat="acme")
        self.assertNotIn("20261023-0900-fix-api-timeout", shown)
        self.assertIn("seat acme's runs only; ak orch list shows every seat's", shown)

    def test_a_seat_with_runs_names_itself(self):
        shown = self.listing(seat="fix-api")
        self.assertIn("20261023-0900-fix-api-timeout", shown)
        self.assertIn("seat fix-api's runs only; ak orch list shows every seat's", shown)

    def test_outside_a_seat_nothing_changes(self):
        shown = self.listing()
        self.assertIn("20261023-0900-fix-api-timeout", shown)
        self.assertNotIn("runs only;", shown)


if __name__ == "__main__":
    unittest.main()
