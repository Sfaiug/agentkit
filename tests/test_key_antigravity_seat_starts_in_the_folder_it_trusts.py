"""An Antigravity seat's agy starts in the folder its launch trusts, each time the seat is opened.

ak hands agy the folder the seat's command line was made in as its one trusted workspace, and has
tmux start that agy there.  tmux takes that folder whole, though it would read a format or a
command's end in its name; and a pane whose own folder is gone, which tmux alone starts in the
home, starts where its agy is told to trust.
Black-box: the program `AK_BIN` names runs `ak orch` from outside through tests/fixtures/akbin.py
on records of tests/fixtures/akseat.py, with an `agy` that says where it started and the settings
it was handed.
"""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

AGY = ('#!/bin/sh\nwhile [ $# -gt 1 ]; do\n'
       '  [ "$1" = --settings ] && { pwd -P; printf "%s\\n" "$2"; } >"$HOME/agy.new"'
       ' && mv "$HOME/agy.new" "$HOME/agy.said"; shift\n'
       'done\n')


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AntigravitySeatStartsInTheFolderItTrusts(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {"acme": "antigravity"})
        self.home.fake("agy", AGY)

    def seat(self, folder):
        """The record of a seat that ran in `folder` and tmux holds no more."""
        return Seat(self.home, model="acme", cwd=self.home.path / "code" / folder, alive=False,
                    record={"conversation": None})

    def open(self, seat):
        """`ak orch` opens the seat: (where its agy started, the folders that agy was handed as
        trusted), once it has ended, so the seat's next opening starts one more in its pane."""
        said = self.home.path / "agy.said"
        said.unlink(missing_ok=True)
        done = self.home.ak("orch", seat.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        pane = f"={seat.name}:"
        # A pane's process is slow to start and to end on a loaded host.
        deadline = time.monotonic() + 300
        while not (said.exists() and self.home.tmux("display-message", "-p", "-t", pane,
                                                    "#{pane_dead}").out.strip() == "1"):
            self.assertLess(time.monotonic(), deadline,
                            self.home.tmux("capture-pane", "-p", "-t", pane).out)
            time.sleep(0.05)
        folder, settings = said.read_text().splitlines()
        return folder, json.loads(settings)["trustedWorkspaces"]

    def test_a_folder_is_opened_whole_whatever_tmux_reads_in_its_name(self):
        # A format, a style, whose `#` tmux keeps, and the `;` that ends a tmux command.
        seat = self.seat("acme#{session_name}#[bold]#S;")
        # Started anew out of its record, then in its pane.
        for _ in range(2):
            self.assertEqual(self.open(seat), (str(seat.cwd), [str(seat.cwd)]))

    def test_a_seat_whose_folder_is_gone_reopens_where_its_agy_trusts(self):
        seat = self.seat("acme")
        self.open(seat)
        seat.cwd.rmdir()
        folder, trusted = self.open(seat)
        self.assertEqual(trusted, [folder])


if __name__ == "__main__":
    unittest.main()
