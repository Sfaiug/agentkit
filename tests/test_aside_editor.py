"""ak's editor, every seat's $VISUAL, keeps the owner's unsent text for a line of ak's and hands
it back whole, and otherwise is the owner's own editor.

A seat whose turn ended on `ak wait` sat once its run merged: the end of the wait could not be
typed while the owner's unsent text held its composer (19 Oct 2026).  A harness hands its
composer to $VISUAL; this editor takes the text out on ak's ask and back on the next.  Offline:
tmux faked in memory; the processes are this test's own.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from agentkit import aside_editor  # noqa: E402

PANE = "%7"


class AsideEditor(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-aside-editor-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.composer = self.root / "composer.md"
        self.options, self.buffers, self.opened = {}, {}, []
        for name, fake in (("_tmux", self.tmux),
                           ("execvp", lambda *argv: self.opened.append(argv))):
            patcher = patch.object(aside_editor if name == "_tmux" else aside_editor.os, name,
                                   side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tmux(self, *args, data=None):
        """The pane's option, read and cleared at once, and its buffers."""
        if args[0] == "show-options":
            return self.options.pop(args[args.index("-t") + 2], "").encode()
        name = args[args.index("-b") + 1]
        if args[0] == "save-buffer":
            return self.buffers.get(name)
        if args[0] == "load-buffer":
            self.buffers[name] = data
        else:
            self.buffers.pop(name, None)
        return b""

    def edit(self, text, ask=None):
        """The harness's own editor key: its composer handed over, and what is left taken."""
        self.composer.write_text(text)
        if ask:
            self.options[aside_editor.ASK] = ask
        with patch.dict(os.environ, {"TMUX_PANE": PANE}):
            aside_editor.edit([str(self.composer)])
        return self.composer.read_text()

    def test_text_set_aside_twice_comes_back_whole_ahead_of_newer_text(self):
        self.assertEqual(self.edit("and add these posts", aside_editor.request("out")), "")
        self.assertEqual(self.edit("then this", aside_editor.request("out")), "")
        self.assertEqual(self.edit("newest", aside_editor.request("back")),
                         "and add these posts\nthen this\nnewest")
        self.assertEqual((self.buffers, self.opened), ({}, []))

    def test_without_a_fresh_ask_it_opens_the_owners_editor_and_keeps_nothing(self):
        stale = f"out {time.time() - aside_editor.FRESH - 5:.0f}"
        with patch.dict(os.environ, {aside_editor.OWNER: "owners-editor"}):
            for ask in (None, stale):
                self.assertEqual(self.edit("mine", ask), "mine")
        self.assertEqual([argv[1][3] for argv in self.opened], ["owners-editor"] * 2)
        self.assertEqual(self.buffers, {})

    def test_a_seat_launch_keeps_the_owners_editor_beside_aks(self):
        self.assertEqual(aside_editor.launch_env({"EDITOR": "nano"}),
                         [f"VISUAL={aside_editor.EDITOR}", f"EDITOR={aside_editor.EDITOR}",
                          f"{aside_editor.OWNER}=nano"])
        # one launched from inside a seat, whose own $VISUAL is ak's
        inside = {"VISUAL": str(aside_editor.EDITOR), aside_editor.OWNER: "vim"}
        self.assertEqual(aside_editor.launch_env(inside)[2], f"{aside_editor.OWNER}=vim")

    def test_a_harness_below_its_launch_is_found_started_with_aks_editor(self):
        env = {key: value for key, value in os.environ.items() if key != "VISUAL"}
        seats = [subprocess.Popen(["sh", "-c", f"{launch}sleep 30 & wait"], env=env)
                 for launch in (f"env VISUAL={aside_editor.EDITOR} ", "")]
        for seat in seats:
            self.addCleanup(seat.wait)
            self.addCleanup(seat.kill)
        time.sleep(0.5)
        self.assertEqual([aside_editor.launched(str(seat.pid)) for seat in seats], [True, False])

    def test_the_script_a_harness_runs_opens_the_owners_editor(self):
        owner = self.root / "owners-editor"
        owner.write_text('#!/bin/sh\necho "the owner edits" >"$1"\n')
        owner.chmod(0o755)
        env = {key: value for key, value in os.environ.items() if key != "TMUX_PANE"}
        subprocess.run([str(aside_editor.EDITOR), str(self.composer)], check=True, timeout=30,
                       env={**env, aside_editor.OWNER: str(owner)})
        self.assertEqual(self.composer.read_text(), "the owner edits\n")


if __name__ == "__main__":
    unittest.main()
