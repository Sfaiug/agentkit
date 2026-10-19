"""Done comes from the plan: a seat at rest whose every plan line is proven reads `done` and
sends one Done card, with nobody running `ak notify done` (owner, 19 Oct 2026).  It sends one
card per piece of work the plan finishes: a later turn over the same plan sends none, its card
file lost or not, and work proven after a declaration sends its own, an open line none.  A done
covering none of the seat's verified work -- a plan holding only what its runs delivered, or a
seat with no creation stamp -- sends none but ends the owner's intent, and a declaration still
cards it.  A seat with no plan finished is `idle`, and one whose plan still owes a line is the
owner's.  A run's merge runs the seat's plan checks, so a line it proved ticks before the seat
hears of it.

Offline: temporary seat state, the real state ladder with the screen read supplied, and a
local webhook.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, handback, harness, notify, orch, plan, watch


class DoneFromThePlan(Sandbox):
    def setUp(self):
        super().setUp()
        self.now = 10000
        self.requests = []
        owner = self

        class Webhook(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                owner.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"id": str(len(owner.requests))}).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Webhook)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.stack.enter_context(patch.dict(os.environ, {
            notify.SINK_ENV: f"http://127.0.0.1:{server.server_port}/hook",
            "AGENTKIT_DISCORD_USER_ID": "", "AK_RUN_ROLE": "", "AGENTKIT_RUN": "",
            "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "CLAUDE_CONFIG_DIR": str(self.root / ".claude"), "CODEX_HOME": str(self.root / ".codex"),
            "GROK_HOME": str(self.root / ".grok"), "XDG_CONFIG_HOME": str(self.root / ".config"),
            "XDG_DATA_HOME": str(self.root / ".local/share")}))
        self.stack.enter_context(patch.object(notify.time, "time", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(1, "fake tmux")))
        decide = watch.session_state

        def at_rest(name, **facts):
            # the screen says the seat sits at its prompt; every other fact is the real ladder's
            record = config.session_records().get(name, {})
            if facts.get("session") is None:
                facts["session"] = {**record, "name": name}
            facts.setdefault("cfg", self.cfg)
            facts.setdefault("harness", orch.seat_plugin(record))
            facts.setdefault("live", {"state": "prompt"})
            for key in ("auth_out", "gh_out", "token_out"):
                facts.setdefault(key, {})
            return decide(name, **facts)

        self.stack.enter_context(patch.object(watch, "session_state", side_effect=at_rest))
        self.name = "fix-api"
        config.save_session(self.cfg, self.name, self.cfg["defaults"]["workers"][0],
                            self.cfg["defaults"]["workers"],
                            {"created": 10, "cwd": str(self.root / "acme"),
                             "conversation": "thread", "id_source": harness.LAUNCHER})

    def plan(self, *lines):
        config.plan_path(self.name).write_text("".join(line + "\n" for line in lines))

    def word(self):
        return watch.session_state(self.name, now=self.now)

    def tick(self):
        self.now += 100
        self.assertEqual(notify.transition(self.name), 0)

    def done_cards(self):
        return [payload for payload in self.requests if payload["content"] == f"✅ Done · {self.name}"]

    def test_a_proven_plan_reads_done_and_cards_once_without_a_declaration(self):
        self.plan("- [x] the API answers · check: `test -f api.txt` · acme · written 2026-10-19 10:00"
                  " · done 0123456789ab", "- [x] the export works")
        state = self.word()
        self.assertEqual((state["word"], state["reason"]), ("done", "the export works"))
        self.tick()
        self.tick()
        self.assertEqual(len(self.done_cards()), 1)
        self.assertIsNone(notify.last(self.name))          # nobody declared it

    def test_a_later_turn_over_the_same_plan_sends_no_second_card(self):
        self.plan("- [x] the API answers")
        self.tick()
        self.now += 100
        self.assertEqual(notify.transition(self.name, answer={
            "word": "working", "reason": "a chat turn", "since": self.now}), 0)
        self.tick()
        self.assertEqual(self.word()["word"], "done")
        self.assertEqual(len(self.done_cards()), 1)
        self.plan("- [x] the API answers", "- [x] the export works")    # new work, finished
        self.tick()
        self.assertEqual(len(self.done_cards()), 2)

    def test_the_outbox_remembers_carded_work_when_the_card_file_is_lost(self):
        self.plan("- [x] the API answers")
        self.tick()
        config.card_path(self.name).unlink()
        self.tick()
        self.assertEqual(len(self.done_cards()), 1)

    def test_work_proven_after_a_declaration_cards_without_another(self):
        self.plan("- [x] the API answers")
        self.assertEqual(notify.shaped("done", "the API answers", session=self.name), 0)
        export = "the export works · check: `test -f export.txt` · acme · written 2026-10-19 10:00"
        self.plan("- [x] the API answers", f"- [ ] {export}")
        self.tick()
        self.assertEqual(len(self.done_cards()), 1)         # an open line is no work yet
        self.plan("- [x] the API answers", f"- [x] {export} · done 0123456789ab")
        self.tick()
        self.assertEqual(len(self.done_cards()), 2)

    def test_a_seat_with_no_creation_stamp_cards_its_declaration(self):
        config.update_session(self.name, created=None)
        self.plan("- [x] the API answers")
        self.tick()
        self.assertEqual(self.done_cards(), [])
        self.assertEqual(notify.shaped("done", "the API answers", session=self.name), 0)
        self.assertEqual(len(self.done_cards()), 1)

    def test_a_plan_only_runs_delivered_ends_the_intent_and_cards_nothing(self):
        repo = self.root / "acme"
        repo.mkdir()
        (repo / "api.txt").write_text("shipped\n")

        def git(*args):
            return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c",
                                   "user.email=test@localhost", *args],
                                  check=True, capture_output=True, text=True).stdout.strip()

        git("init", "-q", "-b", "main")
        git("add", ".")
        git("commit", "-qm", "Ship API")
        sha = git("rev-parse", "HEAD")
        config.update_session(self.name, repo=str(repo))
        self.plan(f"- [x] the API answers · check: `test -f api.txt` · {plan.named(repo)}"
                  f" · deferred · written 1970-01-01 00:01 · done {sha}")
        self.ended("api-fix", owner=self.name, merged=True, repo=str(repo),
                   followup={"check": "test -f api.txt"})
        with patch.object(notify, "_intent") as intent:
            self.tick()
            self.tick()
        self.assertEqual(self.word()["word"], "done")
        intent.assert_called_once()
        late = self.ended("late-run", owner=self.name, state="running", started_at=self.now, pid=0)
        self.tick()
        self.assertEqual(self.word()["word"], "working")
        state = json.loads((late / "run.json").read_text())
        (late / "run.json").write_text(json.dumps({**state, "state": "pass", "reported": True,
                                                    "merged": True, "finished_at": self.now}))
        self.tick()
        self.assertEqual(self.done_cards(), [])

    def test_no_plan_is_idle_and_an_owed_line_is_the_owners(self):
        self.tick()
        self.assertEqual(self.word()["word"], "idle")
        self.plan("- [x] the API answers", "- [ ] the export works")
        state = self.word()
        self.assertEqual((state["word"], state["reason"]),
                         ("needs you", "stopped with work open: the export works"))
        self.tick()
        self.assertEqual(self.done_cards(), [])

    def test_a_merge_runs_the_seat_s_plan_checks(self):
        merged = {"merged": True, "launched_session": self.name}
        with patch.object(plan, "verify") as verify, patch.object(plan, "delivery") as delivery:
            handback.settle_delivered_line(merged, print)
            handback.settle_delivered_line({**merged, "followup": {"check": "test -f fix.txt"}}, print)
            handback.settle_delivered_line({**merged, "merged": False}, print)
        verify.assert_called_once_with(self.name)
        delivery.assert_called_once_with(self.name, "test -f fix.txt")


if __name__ == "__main__":
    unittest.main()
