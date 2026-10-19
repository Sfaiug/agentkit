"""ak's editor, every seat's $VISUAL, keeps the owner's unsent text for a line of ak's and hands
it back whole, and otherwise is the owner's own editor.

A seat whose turn ended on `ak wait` sat once its run merged: the end of the wait could not be
typed while the owner's unsent text held its composer (19 Oct 2026).  A harness hands its
composer to $VISUAL; this editor keeps the text for ak's line on ak's ask and hands it back on
another.  Offline:
tmux faked in memory; the processes are this test's own.
"""

import io
import os
from pathlib import Path
import re
import shlex
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
        self.unreadable, self.given_up = False, False
        for name, fake in (("_tmux", self.tmux),
                           ("execvp", lambda *argv: self.opened.append(argv))):
            patcher = patch.object(aside_editor if name == "_tmux" else aside_editor.os, name,
                                   side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tmux(self, *args, data=None):
        """The pane's option, read and cleared at once and set only where unset, and its
        buffers."""
        if args[0] == "show-options":
            said = self.options.pop(aside_editor.ASK, "").encode()
            if self.given_up:           # ak gives up on the ask while the edit is at it
                self.options[aside_editor.ASK], self.given_up = aside_editor.DONE, False
            return said
        if args[0] == "set-option":
            if args[-2] in self.options:
                return None
            self.options[args[-2]] = args[-1]
            return b""
        if args[0] == "list-buffers":
            return "".join(f"{name}\n" for name in self.buffers).encode()
        name = args[args.index("-b") + 1]
        if args[0] == "save-buffer":
            return None if self.unreadable else self.buffers.get(name)
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

    def test_text_set_aside_twice_comes_back_whole_into_an_empty_composer_alone(self):
        line = aside_editor.request("line", "run done; go on")
        for text in ("", "and add these posts", "then this"):
            self.assertEqual(self.edit(text, line), "run done; go on")
        # never beside the owner's newer text
        self.assertEqual(self.edit("newest", aside_editor.request("back")), "newest")
        self.assertEqual(self.edit("", aside_editor.request("back")),
                         "and add these posts\nthen this")
        self.assertEqual((self.buffers, self.opened), ({}, []))

    def test_text_of_blanks_alone_is_kept_and_given_back_too(self):
        self.edit("  \n", aside_editor.request("line", "go on"))
        self.assertEqual(self.edit("", aside_editor.request("back")), "  \n")

    def test_text_kept_that_cannot_be_read_is_neither_replaced_nor_lost(self):
        self.edit("and add these posts", aside_editor.request("line", "go on"))
        self.unreadable = True      # tmux timed out on the buffer
        self.assertEqual(self.edit("then this", aside_editor.request("line", "go on")),
                         "then this")
        self.assertEqual(self.buffers, {aside_editor.kept(PANE): b"and add these posts"})
        self.assertNotIn(aside_editor.ASK, self.options)   # not done: ak's line goes in later

    def test_a_line_ak_gave_up_on_stays_out_and_the_text_kept_leaves_the_composer(self):
        self.given_up = True
        self.assertEqual(self.edit("and add these posts", aside_editor.request("line", "go on")),
                         "")
        self.assertEqual(self.edit("", aside_editor.request("back")), "and add these posts")

    def test_without_a_fresh_ask_it_opens_the_owners_editor_and_keeps_nothing(self):
        stale = f"line {time.time() - aside_editor.FRESH - 5:.0f} go on"
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

    def test_a_seat_is_told_by_its_launch_not_by_what_its_harness_runs(self):
        # each seat's wrapper, on the pane's terminal, runs its harness on another, and the
        # harness a tool given ak's editor; tmux's shell is above the wrapper or execed into it
        terminal, pane = os.openpty()
        for end in (terminal, pane):
            self.addCleanup(os.close, end)
        tool = shlex.join(["env", f"VISUAL={aside_editor.EDITOR}", "sh", "-c",
                           "echo up; exec sleep 30"])
        harness = shlex.join(["sh", "-c", f"{tool} & wait"]) + " </dev/null"
        env = {key: value for key, value in os.environ.items() if key != "VISUAL"}
        seats = []
        for shell in (True, False):
            for visual in (aside_editor.EDITOR, "nano"):
                launch = ["env", f"VISUAL={visual}", "sh", "-c", f"{harness} & wait"]
                seats.append(subprocess.Popen(
                    ["sh", "-c", shlex.join(launch) + "; wait"] if shell else launch, stdin=pane,
                    stdout=subprocess.PIPE, start_new_session=True, env=env))
        for seat in seats:
            self.addCleanup(seat.stdout.close)
            self.addCleanup(seat.wait)
            self.addCleanup(os.killpg, seat.pid, 9)
            self.assertEqual(seat.stdout.readline(), b"up\n")
        opened = io.open

        def without_children(file, *args, **kwargs):
            # a kernel built without CONFIG_PROC_CHILDREN lists no task's children
            if re.fullmatch(r"/proc/\d+/task/\d+/children", str(file)):
                raise FileNotFoundError(2, "No such file or directory", str(file))
            return opened(file, *args, **kwargs)

        with patch.object(io, "open", without_children):
            self.assertEqual([aside_editor.launched(str(seat.pid), os.ttyname(pane))
                              for seat in seats], [True, False, True, False])

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
