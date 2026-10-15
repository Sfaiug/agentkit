"""`ak orch stop` keeps the seat: its record and state files stay with the stop mark, written
before the tmux session goes, the listing offers it with `closed` set for its number to reopen
it -- whether or not its harness can resume it -- its name stays taken, and the card `x` asks on
says so.  A second stop takes it off the list: the record, every state file but the locks, the
pointers a rename left and what its harness held, and the name is free again; the stop mark
alone comes back into the seat file, nothing else of its live state with it.

Offline: a throwaway HOME, tmux faked, no runs and no real seat.
"""

from contextlib import redirect_stdout
import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixtures.sandbox import Sandbox
from agentkit import browser, config, menu, orch, statusbar, watch

OLD, SEAT = "acme", "acme-ui"           # the seat was started as `acme` and renamed
KINDS = ("plan", "rulebook", "hook", "notify", "compact", "stop")


class StopKeepsTheSeat(Sandbox):
    def setUp(self):
        super().setUp()
        os.environ.pop(config.SESSION_ENV, None)      # the owner, who may stop any seat
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_NOTIFY_SINK": ""}))
        self.tmux = []
        self.stack.enter_context(patch.object(
            orch, "tmux_out", side_effect=lambda *args, **kw: self.tmux.append(args) or (0, "")))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(browser, "close_tab"))
        config.save_session(self.cfg, OLD, self.cfg["defaults"]["orchestrator"],
                            self.cfg["defaults"]["workers"],
                            {"cwd": str(self.root), "created": 100, "conversation": "conv-1",
                             "id_source": "launcher"})
        config.rename_session(OLD, SEAT)
        for kind in KINDS:
            config.seat_file(kind, SEAT).write_text(
                "{}\n" if config.SEAT_FILES[kind] == "json" else "- [ ] a line\n")
        self.lock = config.notify_path(SEAT).with_suffix(".lock")
        self.lock.write_text("")

    def stop(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(orch.cmd_stop([SEAT]), 0)
        return out.getvalue()

    def test_a_stop_keeps_the_seat_for_its_number_to_reopen(self):
        said = self.stop()
        self.assertEqual(said, f"stopped {SEAT}; its number reopens it for a week\n")
        self.assertTrue(config.session_path(SEAT).exists())
        self.assertEqual(config.session_records()[SEAT]["conversation"], "conv-1")
        for kind in KINDS:
            self.assertTrue(config.seat_file(kind, SEAT).exists(), kind)
        seat = watch.seat_read(SEAT)
        self.assertTrue(seat.get("closed_by_owner"))
        self.assertTrue(seat.get("stopped_at"))
        # the listing offers it, closed, and its number is the way back into the conversation
        rows = orch.listing(reconcile=False)
        self.assertEqual([(row["name"], row["resumable"], row["closed"]) for row in rows],
                         [(SEAT, True, seat["stopped_at"])])
        self.assertTrue(orch.resumable(config.session_records()[SEAT]))
        self.assertIn(SEAT, orch.taken_names())
        self.assertIn(OLD, orch.taken_names())           # the pointer still leads to it
        # the hand-back of a run of its waits for that reopening, and nothing was killed
        self.assertTrue(watch.seat_closed_by_owner(SEAT))
        self.assertNotIn("kill-session", [args[0] for args in self.tmux])

    def test_a_second_stop_removes_the_seat_and_frees_its_name(self):
        self.stop()
        watch.seat_write(SEAT, wait={"on": "https://github.com/acme/acme/pull/7", "kind": "pr"})
        stopped = watch.seat_read(SEAT)["stopped_at"]
        plugin = MagicMock()
        plugin.reconcile.return_value = {}
        with patch.object(orch, "seat_plugin", side_effect=lambda record: plugin):
            said = self.stop()
        self.assertEqual(said, f"removed {SEAT}\n")
        self.assertFalse(config.session_path(SEAT).exists())
        self.assertFalse(config.session_path(OLD).exists())   # the pointer went with it
        for kind in KINDS:
            self.assertFalse(config.seat_file(kind, SEAT).exists(), kind)
        self.assertTrue(self.lock.exists())              # a reopened name keeps its lock inodes
        # the stop mark alone stays: a hand-back of its runs waits on it rather than ask the
        # owner to continue a seat they removed, and a seat opened under the name is told
        # nothing of this one's wait; the collector takes the mark a day later
        self.assertEqual(watch.seat_read(SEAT), {"session": SEAT, "stopped_at": stopped,
                                                 "closed_by_owner": True})
        plugin.forget.assert_called_once()
        self.assertEqual(plugin.forget.call_args[0][0]["conversation"], "conv-1")
        self.assertEqual(orch.listing(reconcile=False), [])
        self.assertNotIn(SEAT, orch.taken_names())
        self.assertNotIn(OLD, orch.taken_names())

    def test_a_seat_tmux_lost_on_its_own_is_stopped_first_and_removed_second(self):
        # no stop mark yet: the first stop closes it like any other, the second takes it
        self.assertFalse(watch.seat_closed_by_owner(SEAT))
        self.stop()
        self.assertTrue(config.session_path(SEAT).exists())
        self.stop()
        self.assertFalse(config.session_path(SEAT).exists())

    def test_a_stopped_seat_its_harness_cannot_resume_keeps_its_row(self):
        # no conversation to come back on: before the stop it had no row, after it the row is
        # what `x` removes it by and what keeps its name taken, and its number starts fresh
        fresh = "acme-fresh"
        config.save_session(self.cfg, fresh, self.cfg["defaults"]["orchestrator"],
                            self.cfg["defaults"]["workers"], {"cwd": str(self.root), "created": 100})
        self.assertFalse(orch.resumable(config.session_records()[fresh]))
        self.assertNotIn(fresh, {row["name"] for row in orch.listing(reconcile=False)})
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.cmd_stop([fresh]), 0)
        rows = {row["name"]: row for row in orch.listing(reconcile=False)}
        self.assertEqual((rows[fresh]["resumable"], rows[fresh]["restart"],
                          rows[fresh]["closed"]), (False, "starts fresh",
                                                   watch.seat_stopped_at(fresh)))
        self.assertIn(fresh, orch.taken_names())

    def test_the_stop_mark_is_in_place_before_the_session_is_killed(self):
        # a hand-back that meets the session gone finds the seat closed, never a ghost to reopen
        marked = []
        session = {"name": SEAT, "path": str(self.root), "created": 100,
                   "attached": False, "exited": False, "legacy": False}

        def tmux(*args, **_kw):
            if args[0] == "kill-session":
                marked.append(watch.seat_closed_by_owner(SEAT))
            return 0, ""

        with patch.object(orch, "sessions", return_value=[session]), \
                patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(statusbar, "retell"):
            self.stop()
        self.assertEqual(marked, [True])

    def test_the_card_says_the_seat_stays_and_how_it_goes(self):
        tail = ("with it; the session stays listed for a week: its number reopens it, "
                "x on it again removes it now.")
        self.assertEqual(menu.stop_means(None), f"Its runs stop {tail}")
        self.assertEqual(menu.stop_means(0), f"No runs stop {tail}")
        self.assertEqual(menu.stop_means(1), f"1 run stops {tail}")
        self.assertEqual(menu.stop_means(3), f"3 runs stop {tail}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
