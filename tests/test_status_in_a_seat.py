"""In a seat, `ak run status` lists that seat's own runs, under one host line; offline."""

from contextlib import redirect_stdout
import io
import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gate, status


class StatusInASeat(Sandbox):
    def setUp(self):
        super().setUp()
        self.ended("20261020-0900-acme-login", owner="acme")
        self.ended("20261020-0910-review-pr-acme-7", owner="acme")
        self.ended("20261020-0920-fix-api-timeout", owner="fix-api")
        self.host = gate.host_status_line().splitlines()[0]

    def listing(self, *argv, seat=None):
        out = io.StringIO()
        with patch.dict(os.environ, {config.SESSION_ENV: seat} if seat else {}), \
                redirect_stdout(out):
            self.assertEqual(status.cmd_status(list(argv)), 0)
        return out.getvalue()

    def test_a_seat_lists_its_own_runs_under_one_host_line(self):
        for argv in ((), ("--plain",)):
            shown = self.listing(*argv, seat="acme")
            self.assertIn("20261020-0900-acme-login", shown)
            self.assertIn("20261020-0910-review-pr-acme-7", shown)
            self.assertNotIn("20261020-0920-fix-api-timeout", shown)
            self.assertEqual(shown.count(self.host), 1, shown)

    def test_outside_a_seat_every_run_shows(self):
        shown = self.listing()
        for name in ("20261020-0900-acme-login", "20261020-0920-fix-api-timeout"):
            self.assertIn(name, shown)
        self.assertEqual(shown.count(self.host), 1, shown)

    def test_any_run_shows_by_its_id(self):
        self.assertIn("20261020-0920-fix-api-timeout",
                      self.listing("20261020-0920-fix-api-timeout", seat="acme"))


if __name__ == "__main__":
    unittest.main()
