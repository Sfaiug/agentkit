"""A client is refused a session before it writes: each way to one asks `orch.refuse_client`
first.

`orch.resume` and `orch.ensure(saved=True)`, for a seat tmux lost, and `orch.ensure` and
`orch.create`, for a new one, each raise naming the home and leave HOME as it was: they ask
before they write, and before they read through `orch.records`, which writes what a harness
reconciles.  So HOME holds a seat's record whose conversation no launch handed out, which its
harness reconciling drops, and the name that seat had before a rename, for which `create`, given
no names taken, lists the seats.  `resume` asks before it reads what tmux holds too, which it
does only after `orch.records`: a seat whose pane tmux still holds is refused as one it lost.
So does `orch.reopen`, which a pane's end calls as well, before it marks a seat whose end cut
off a question as asking again.

`orch.switch_orchestrator`, for a seat tmux lost, names the home in its one line and leaves HOME
as it was but for the locks its try at a move in place took: it asks outside what puts a handover
back, and before the seat's record or its rulebook is written.

A machine install.sh makes a client while `resume` reads tmux, or the efforts its command runs
at, or while the move reads the seat's handover, is refused as well, before the seat's rulebook is
written: `resume` asks again before its command is built, and the move asks only after that read.

`orch.start` itself refuses a caller that did not ask, as one added later would, before it asks
tmux for anything.

`ak orch` from outside is tests/test_key_a_client_opens_no_session.py's.
Offline: fixtures.sandbox's HOME, where tmux holds no seat.
"""

import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch, watch


class AClient(Sandbox):
    def setUp(self):
        super().setUp()
        for name, source in (("acme", orch.LAUNCHER), ("ship-docs", "legacy")):
            config.save_session(self.cfg, name, "fable", ["opus"], {
                "cwd": str(self.root), "conversation": f"conv-{name}", "id_source": source})
        config.rename_session("ship-docs", "docs")
        (config.STATE / "server").write_text("acme-box\n")

    def tree(self):
        return {path: path.read_bytes() if path.is_file() else None
                for path in sorted(self.root.rglob("*"))}

    def assertRefused(self, ask):
        before = self.tree()
        with self.assertRaisesRegex(config.Error, "acme-box"):
            ask()
        self.assertEqual(self.tree(), before)

    def test_a_seat_tmux_lost_is_refused_before_a_record_is_reconciled(self):
        self.assertRefused(lambda: orch.resume(self.cfg, "acme", hand_over=False))
        self.assertRefused(lambda: orch.ensure(self.cfg, "acme", saved=True))

    def test_resume_refuses_whatever_tmux_holds_of_the_seat(self):
        with patch.object(orch, "find", side_effect=AssertionError("tmux was asked")):
            self.assertRefused(lambda: orch.resume(self.cfg, "acme", hand_over=False))

    def test_a_reopen_is_refused_before_the_seat_is_marked_as_asking_again(self):
        with patch.object(watch, "cut_off", return_value=("turn", watch.ASKED_LINE)):
            self.assertRefused(lambda: orch.reopen(self.cfg, "acme"))

    def test_a_new_seat_is_refused_before_a_record_is_reconciled_or_written(self):
        self.assertRefused(lambda: orch.ensure(self.cfg, "fix-api"))
        self.assertRefused(lambda: orch.create(self.cfg, "fix-api", self.root, "fable", "opus",
                                               prompting=False))

    def test_a_seat_tmux_lost_is_not_moved_to_another_model(self):
        # all but the locks its try at a move in place took, which stay as they do on a home
        unlocked = lambda: {path: data for path, data in self.tree().items()
                            if path.suffix not in (".lock", ".announce")}
        before = unlocked()
        with patch.object(orch, "_switch_plan", return_value=("", None)), \
                patch.object(orch, "unhanded", side_effect=AssertionError("a handover put back")):
            said = orch.switch_orchestrator(self.cfg, "acme", "opus", providers={})
        self.assertIn("acme-box", said)
        self.assertEqual(unlocked(), before)

    @contextmanager
    def made_a_client_by(self, owner, read, when=lambda *args: True):
        """`owner.read` records a server once it has answered, where `when` says so of what it was
        asked, as install.sh may while it is read: HOME has none till then.  A rulebook written
        meanwhile fails the test."""
        server, real = config.STATE / "server", getattr(owner, read)
        server.unlink()

        def answers(*args, **kw):
            try:
                return real(*args, **kw)
            finally:
                if when(*args):
                    server.write_text("acme-box\n")

        unwritten = patch.object(orch, "write_rulebook",
                                 side_effect=AssertionError("a rulebook written"))
        with patch.object(owner, read, answers), unwritten:
            yield

    def test_resume_refuses_a_machine_made_a_client_while_it_read(self):
        # tmux, where the seat is lost, and the last it reads: the efforts its command runs at
        for owner, read in ((orch, "find"), (config, "at_efforts")):
            with self.subTest(read=read), self.made_a_client_by(owner, read):
                with self.assertRaisesRegex(config.Error, "acme-box"):
                    orch.resume(self.cfg, "acme", hand_over=False)

    def test_a_move_refuses_a_machine_made_a_client_while_it_read_the_handover(self):
        handed = config.seat_file("handover", "acme")
        with self.made_a_client_by(Path, "read_bytes", lambda path: path == handed), \
                patch.object(orch, "_switch_plan", return_value=("", None)), \
                patch.object(orch, "unhanded", side_effect=AssertionError("a handover put back")):
            said = orch.switch_orchestrator(self.cfg, "acme", "opus", providers={})
        self.assertIn("acme-box", said)

    def test_start_refuses_a_caller_that_did_not_ask_before_it_asks_tmux(self):
        with patch.object(orch, "tmux_out", side_effect=AssertionError("tmux was asked")):
            self.assertRefused(lambda: orch.start("acme", self.root, ["true"], "opus"))


if __name__ == "__main__":
    unittest.main()
