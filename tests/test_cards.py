"""Session-state transition cards: one latch, one episode, one delivery."""

from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import config, notify, orch, watch


class Cards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".cards-")
        self.root = Path(self.tmp.name)
        home = self.root / ".agentkit"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.tmp.cleanup)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name,
                                                  home if name == "HOME" else home / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "seat", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AK_NOTIFY_SINK": "off", "AK_RUN_ROLE": ""}, clear=False))
        config.ensure_dirs()
        self.posts = []
        def post(payload, files, message, receipt):
            self.posts.append(payload)
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))

    def answer(self, word, since, reason="question"):
        return {"word": word, "since": since, "reason": reason}

    def run_fixture(self, name, state, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        record = {"state": state, "launched_session": "seat", "title": name, **extra}
        (directory / "run.json").write_text(json.dumps(record))
        return directory

    def test_needs_card_after_sixty_seconds_held(self):
        notify.record("seat", "needs", "Choose a branch", time=100)
        notify.transition("seat", self.answer("needs you", 100), now=159)
        self.assertEqual(self.posts, [])
        notify.transition("seat", self.answer("needs you", 100), now=160)
        self.assertEqual(self.posts[0]["embeds"][0]["title"], "Needs you · seat")

    def test_no_card_while_a_client_is_attached(self):
        notify.record("seat", "needs", "Choose a branch", time=100)
        with patch.object(orch, "tmux_out", return_value=(0, "/dev/pts/1\tseat")):
            notify.transition("seat", self.answer("needs you", 100), now=200)
        self.assertEqual(self.posts, [])

    def test_needs_card_is_one_per_episode(self):
        notify.record("seat", "needs", "Choose a branch", time=100)
        notify.transition("seat", self.answer("needs you", 100), now=200)
        notify.transition("seat", self.answer("needs you", 300), now=300)
        self.assertEqual(len(self.posts), 1)

    def test_new_needs_episode_sends_again(self):
        notify.record("seat", "needs", "First", time=100)
        notify.transition("seat", self.answer("needs you", 100), now=200)
        notify.transition("seat", self.answer("working", 250), now=250)
        notify.record("seat", "needs", "Second", time=300)
        notify.transition("seat", self.answer("needs you", 300), now=360)
        self.assertEqual(len(self.posts), 2)

    def test_done_card_waits_until_no_run_is_unfinished(self):
        directory = self.run_fixture("job", "running")
        self.assertEqual(notify.main(["done", "Finished", "--session", "seat"]), 0)
        self.assertEqual(self.posts, [])   # the word is working while the run goes
        record = json.loads((directory / "run.json").read_text())
        record.update(state="pass", finished_at=time.time())
        (directory / "run.json").write_text(json.dumps(record))
        with patch.object(orch, "listing", return_value=[{"name": "seat"}]):
            notify.tick_cards()
        self.assertEqual(self.posts[0]["embeds"][0]["title"], "Done · seat")

    def test_failed_run_drops_declaration_with_one_log_line(self):
        directory = self.run_fixture("job", "running")
        self.assertEqual(notify.main(["done", "Finished", "--session", "seat"]), 0)
        self.assertEqual(self.posts, [])
        record = json.loads((directory / "run.json").read_text())
        record.update(state="fail", finished_at=time.time())
        (directory / "run.json").write_text(json.dumps(record))
        with io.StringIO() as err, patch("sys.stdout", err), \
                patch.object(orch, "listing", return_value=[{"name": "seat"}]):
            notify.tick_cards()
            notify.tick_cards()
            self.assertEqual(err.getvalue().count("dropping done declaration"), 1)
        self.assertTrue(notify.last("seat", include_seen=True).get("seen"))
        self.assertEqual(self.posts, [])

    def test_notify_needs_records_and_sends_in_the_same_call(self):
        with patch.object(watch, "session_state", return_value=self.answer("needs you", 100)), \
                patch.object(notify.time, "time", return_value=200):
            self.assertEqual(notify.main(["needs", "Choose a branch"]), 0)
        self.assertEqual(notify.last("seat", include_seen=True)["text"], "Choose a branch")
        self.assertEqual(len(self.posts), 1)

    def test_tick_sends_a_word_that_changed_between_ticks(self):
        with patch.object(orch, "listing", return_value=[{"name": "seat"}]), \
                patch.object(watch, "session_state", side_effect=[
                    self.answer("working", 100), self.answer("done", 200, "Finished")]):
            notify.tick_cards()
            notify.record("seat", "done", "Finished", time=200)
            notify.tick_cards()
        self.assertEqual(len(self.posts), 1)

    def test_worker_is_refused(self):
        with patch.dict(os.environ, {"AK_RUN_ROLE": "worker"}):
            self.assertEqual(notify.main(["needs", "Choose a branch"]), 0)
        self.assertFalse(config.notify_path("seat").exists())

    def test_notify_needs_sends_through_the_real_session_state(self):
        watch.seat_write("seat", word="working", reason="", word_since=100)
        self.assertEqual(notify.main(["needs", "Choose a branch"]), 0)
        self.assertEqual(len(self.posts), 1)
        self.assertTrue(json.loads(config.card_path("seat").read_text())["sent"])

    def test_attached_episode_is_retired_without_a_card(self):
        notify.record("seat", "needs", "Choose a branch", time=100)
        with patch.object(orch, "tmux_out", return_value=(0, "/dev/pts/1\tseat")):
            notify.transition("seat", self.answer("needs you", 100), now=200)
        self.assertEqual(self.posts, [])
        self.assertEqual(json.loads(config.card_path("seat").read_text())["closed"], "Answered")
        notify.transition("seat", self.answer("needs you", 100), now=400)   # detached, still held
        self.assertEqual(self.posts, [])   # the seen episode stays quiet

    def test_done_fail_summary_is_red(self):
        notify.record("seat", "done", "FAIL: tests", time=100)
        notify.transition("seat", self.answer("done", 100, "FAIL: tests"), now=100)
        self.assertEqual(self.posts[0]["embeds"][0]["color"], notify.COLORS["fail"])

    def test_legacy_seat_never_cards(self):
        seats = [{"name": "my-editor", "legacy": True}]
        with patch.object(orch, "listing", return_value=seats), \
                patch.object(notify, "terminal_notice") as toast, \
                patch.object(watch, "session_state", side_effect=[
                    self.answer("needs you", 100), self.answer("done", 100, "Finished"),
                    self.answer("needs you", 100), self.answer("done", 100, "Finished")]):
            notify.tick_cards()
            notify.tick_cards()
        self.assertEqual(self.posts, [])
        self.assertFalse(config.card_path("my-editor").exists())
        toast.assert_not_called()

    def test_attached_asks_the_seats_own_server(self):
        sockets = []
        def fake_tmux(*argv, socket=None, **kwargs):
            sockets.append(socket)
            return (0, "")
        seat = {"name": "my-editor", "legacy": True}
        with patch.object(orch, "find", return_value=seat), \
                patch.object(orch, "tmux_out", side_effect=fake_tmux), \
                patch.object(notify, "terminal_notice"):
            notify.transition("my-editor", self.answer("needs you", 100), now=200)
        self.assertEqual(sockets, [orch.seat_socket(seat)])
        self.assertEqual(len(self.posts), 1)   # an explicit command still names its subject

    def test_resolved_done_opens_a_new_episode(self):
        self.assertEqual(notify.main(["done", "First job", "--session", "seat"]), 0)
        self.assertEqual(len(self.posts), 1)
        notify.clear("seat")
        self.assertEqual(notify.main(["done", "Second job", "--session", "seat"]), 0)
        self.assertEqual(len(self.posts), 2)

    def test_done_card_waits_on_a_run_awaiting_recovery(self):
        directory = self.run_fixture("job", "interrupted")
        self.assertEqual(notify.main(["done", "Finished", "--session", "seat"]), 0)
        self.assertEqual(self.posts, [])   # the word is working while recovery is pending
        word = watch.session_state("seat")
        self.assertEqual(word["word"], "working")
        self.assertEqual(word["reason"], "run job awaits recovery")
        record = json.loads((directory / "run.json").read_text())
        record["recovery_acknowledged_at"] = time.time()
        (directory / "run.json").write_text(json.dumps(record))
        with patch.object(orch, "listing", return_value=[{"name": "seat"}]):
            notify.tick_cards()
        self.assertEqual(self.posts[0]["embeds"][0]["title"], "Done · seat")

    def test_no_card_for_a_seat_the_owner_closed(self):
        # `x`, `ak orch stop` or a pause script: the seat is gone on purpose, and nobody
        # in it is asking him anything.  A seat that went on its own is still carded.
        orch.mark_owner_closed("seat")
        for name in ("seat", "crashed"):
            gone = {"name": name, "exited": True}
            notify.transition(name, now=time.time(), seat=gone)
            notify.transition(name, now=time.time() + notify.CARD_WAIT, seat=gone)
        self.assertEqual([post["embeds"][0]["title"] for post in self.posts],
                         ["Needs you · crashed"])
        # ... and the menu still shows it, with the number that reopens it
        found = watch.session_state("seat", session={"name": "seat", "exited": True}, number=3)
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], "session closed by the owner: press 3 to reopen")

    def test_no_card_for_an_episode_older_than_the_install(self):
        now = time.time()
        self.assertEqual(notify.installed_at(), 0)          # no install stamped this home
        (config.STATE / "installed-at").write_text(f"{now - 600}\n")
        self.assertGreaterEqual(notify.installed_at(), now - 600)
        cfg = config.load()
        with patch.object(notify, "installed_at", return_value=now - 600):
            # a question standing since before the install, first read by this version
            notify.record("seat", "needs", "Choose a branch", time=now - 3600)
            notify.transition("seat", self.answer("needs you", now - 3600), now=now)
            # ... a pane that died before it, whichever tick first reads it gone, and a
            # seat tmux lost long before it
            config.save_session(cfg, "gone", "fable", ["opus"], {"exited_since": now - 7200})
            config.save_session(cfg, "lost", "fable", ["opus"], {"seen": now - 3 * 86400})
            # ... and a done declared before it
            notify.record("finished", "done", "Shipped", time=now - 3600)
            notify.transition("finished", self.answer("done", now - 3600, "Shipped"), now=now)
            # A seat last seen alive shortly before the install may have gone after it: its
            # record is renewed only every few minutes, so it is still news.
            config.save_session(cfg, "vanished", "fable", ["opus"], {"seen": now - 700})
            # ... unless its record says its pane died before it, which outlives the pane
            config.save_session(cfg, "dropped", "fable", ["opus"],
                                {"seen": now - 700, "exited_since": now - 690})
            for seat in ({"name": "gone", "exited": True}, {"name": "lost", "resumable": True},
                         {"name": "vanished", "resumable": True},
                         {"name": "dropped", "resumable": True}):
                notify.transition(seat["name"], now=now, seat=seat)
                notify.transition(seat["name"], now=now + notify.CARD_WAIT, seat=seat)
            self.assertEqual([post["embeds"][0]["title"] for post in self.posts],
                             ["Needs you · vanished"])
            self.assertEqual(json.loads(config.card_path("gone").read_text())["began"],
                             now - 7200)
            # A word that begins after the install is news as ever.
            notify.transition("seat", self.answer("working", now), now=now)
            notify.transition("seat", self.answer("needs you", now), now=now + notify.CARD_WAIT)
        self.assertEqual([post["embeds"][0]["title"] for post in self.posts],
                         ["Needs you · vanished", "Needs you · seat"])

    def test_an_episode_opened_before_the_install_is_not_sent_after_it(self):
        # opened by the version before, still inside its minute when the install landed
        now = time.time()
        notify.record("seat", "needs", "Choose a branch", time=now - 100)
        notify.transition("seat", self.answer("needs you", now - 100), now=now - 90)
        with patch.object(notify, "installed_at", return_value=now - 50):
            notify.transition("seat", self.answer("needs you", now - 100), now=now)
        self.assertEqual(self.posts, [])

    def test_a_queued_card_is_not_sent_late_against_the_rules(self):
        # Discord was down: the retry is the card sent late, and the rules hold for it too.
        def down(payload, files, message, receipt):
            receipt.update(status="pending", error="down")
            return 0
        with patch.object(notify, "post", side_effect=down):
            self.assertEqual(notify.main(["needs", "Choose a branch"]), 0)
            installed = time.time()
            for name in ("other", "third"):
                self.assertEqual(notify.main(["needs", "Pick one", "--session", name]), 0)
            self.assertEqual(notify.main(["done", "Shipped", "--session", "paused"]), 0)
        orch.mark_owner_closed("other")
        orch.mark_owner_closed("paused")
        logs = []
        with patch.object(notify, "installed_at", return_value=installed), \
                patch.object(notify.time, "time", return_value=installed + 3600):
            notify.retry_pending(log=logs.append)
            notify.retry_pending(log=logs.append)
        self.assertEqual([post["embeds"][0]["title"] for post in self.posts],
                         ["Needs you · third"])
        events = {event["session"]: event for event in
                  (json.loads(path.read_text()) for path in notify.outbox().glob("*.json"))}
        self.assertEqual([events[name]["status"] for name in ("seat", "other", "paused")],
                         ["disabled"] * 3)
        self.assertEqual(len(logs), 3)

    def test_notify_is_news_even_where_the_standing_episode_is_history(self):
        # `ak notify` is the visible start of its episode, however long the word it lands
        # on has stood: explicit needs and done keep working as they did.
        now = time.time()
        watch.seat_write("seat", word="needs you", reason="waiting for you",
                         word_since=now - 3600)
        with patch.object(notify, "installed_at", return_value=now - 600):
            notify.transition("seat", self.answer("needs you", now - 3600), now=now)
            notify.record("finished", "done", "Shipped", time=now - 3600)
            notify.transition("finished", self.answer("done", now - 3600, "Shipped"), now=now)
            self.assertEqual(self.posts, [])
            self.assertEqual(notify.main(["needs", "Choose a branch"]), 0)
            self.assertEqual(notify.main(["done", "Shipped again", "--session", "finished"]), 0)
            # ... and on a seat with no episode yet
            watch.seat_write("fresh", word="needs you", word_since=now - 3600)
            self.assertEqual(notify.main(["needs", "Which one?", "--session", "fresh"]), 0)
        self.assertEqual([post["embeds"][0]["title"] for post in self.posts],
                         ["Needs you · seat", "Done · finished", "Needs you · fresh"])

    def test_a_done_is_carded_once_however_often_its_word_comes_back(self):
        notify.record("seat", "done", "Finished", time=100)
        notify.transition("seat", self.answer("done", 100, "Finished"), now=100)
        # a run of its own awaits recovery and is acknowledged: the same ending again
        notify.transition("seat", self.answer("working", 200), now=200)
        notify.transition("seat", self.answer("done", 300, "Finished"), now=300)
        self.assertEqual(len(self.posts), 1)
        # A new declaration is a new ending.
        notify.transition("seat", self.answer("working", 400), now=400)
        notify.record("seat", "done", "Finished again", time=500)
        notify.transition("seat", self.answer("done", 500, "Finished again"), now=500)
        self.assertEqual([post["embeds"][0]["title"] for post in self.posts],
                         ["Done · seat", "Done · seat"])

    def test_a_done_is_carded_once_across_versions_episodes_and_names(self):
        # A done card the version before sent, keyed its own way, whose word it had already
        # moved on before this install: the outbox still holds it, and it is this ending's.
        notify.record("seat", "done", "Finished", time=100)
        notify.outbox().mkdir(parents=True, exist_ok=True)
        (notify.outbox() / "old.json").write_text(json.dumps(
            {"id": "old", "source": "", "session": "seat", "kind": "done", "text": "Finished",
             "created_at": 101, "status": "delivered"}))
        config.card_path("seat").write_text(json.dumps(
            {"word": "working", "since": 150, "episode": "e", "sent": False, "open_needs": []}))
        notify.transition("seat", self.answer("done", 300, "Finished"), now=300)
        self.assertEqual(self.posts, [])
        # An explicit done over a done episode that is history is sent, and once.
        now = time.time()
        with patch.object(notify, "installed_at", return_value=now - 600):
            notify.record("finished", "done", "Shipped", time=now - 3600)
            notify.transition("finished", self.answer("done", now - 3600, "Shipped"), now=now)
            self.assertEqual(notify.main(["done", "Shipped again", "--session", "finished"]), 0)
            notify.transition("finished", self.answer("working", now), now=now)
            notify.transition("finished", self.answer("done", now, "Shipped again"), now=now)
        # ... and one sent under the old name is the same ending under the new one.
        notify.record("other", "done", "Shipped", time=400)
        notify.transition("other", self.answer("done", 400, "Shipped"), now=400)
        config.rename_session("other", "renamed")
        notify.transition("renamed", self.answer("working", 500), now=500)
        notify.transition("renamed", self.answer("done", 600, "Shipped"), now=600)
        self.assertEqual([post["embeds"][0]["title"] for post in self.posts],
                         ["Done · finished", "Done · other"])

if __name__ == "__main__":
    unittest.main()
