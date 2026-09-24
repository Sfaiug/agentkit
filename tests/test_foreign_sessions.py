"""A tmux session with no agent in it is not a seat, and a card whose seat is gone is closed.

Real tmux on a private `-L agentkit-test` server under a throwaway TMUX_TMPDIR, killed in
cleanup, and a fake webhook on a local port that hears every edit: nothing here reaches the
owner's tmux server, Discord or ~/.agentkit.
"""

from contextlib import ExitStack, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import config, notify, orch
from agentkit.harness import LAUNCHER

LOOP = "while :; do sleep 60; done"   # the watcher an orchestrator left behind: no agent


class ForeignSessions(unittest.TestCase):
    def setUp(self):
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        # under /tmp, not the checkout: the socket path has to fit in sockaddr_un
        tmp = tempfile.TemporaryDirectory(prefix="ak-foreign-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.requests, self.codes = [], []   # codes: what Discord answers, 200 once they run out
        owner = self

        class Hook(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_PATCH(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                owner.requests.append((self.command, self.path, json.loads(raw)))
                self.send_response(owner.codes.pop(0) if owner.codes else 200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            do_POST = do_PATCH

        server = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_port}/api/webhooks/1/token"
        sockets = self.root / "s"
        sockets.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "TMUX_TMPDIR": str(sockets), orch.SOCKET_ENV: "agentkit-test",
            "AGENTKIT_DISCORD_WEBHOOK": self.url, "AK_NOTIFY_SINK": "", "AK_RUN_ROLE": "",
            "AGENTKIT_SESSION": "", config.ADAPTER_DIR_ENV: ""}))
        os.environ.pop("TMUX", None)   # the sandbox's environment is restored on the way out
        self.env = dict(os.environ)
        self.addCleanup(subprocess.run, ["tmux", "-L", "agentkit-test", "kill-server"],
                        env=self.env, capture_output=True)
        orch._PROCESSES.clear()
        self.addCleanup(orch._PROCESSES.clear)
        config.ensure_dirs()
        self.cfg = config.load()
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def tmux(self, *args):
        return subprocess.run(["tmux", "-L", "agentkit-test", "-f", "/dev/null", *args],
                              env=self.env, check=True, capture_output=True, text=True).stdout

    def listed(self):
        return {session["name"]: session for session in orch.listing(reconcile=False)}

    def agent(self):
        """A fake harness binary: a script named for one an adapter launches."""
        agent = self.bin / "claude"
        agent.write_text("#!/bin/sh\nwhile :; do sleep 1; done\n")
        agent.chmod(0o755)
        return agent

    def until_listed(self, *names):
        """Wait for those panes to have exec'd what they were started with, and be seats."""
        deadline = time.monotonic() + 10
        while not set(names) <= set(self.listed()) and time.monotonic() < deadline:
            orch._PROCESSES.clear()
            time.sleep(0.05)
        orch._PROCESSES.clear()
        return self.listed()

    def card(self, name):
        """A card as the tick left one: `needs you`, sent, and its Discord message standing."""
        embed = {"title": f"Needs you · {name}", "color": 16753920,
                 "fields": [{"name": "open", "value": "press 1"}]}
        pending = {"message_id": "4242", "webhook": hashlib.sha256(self.url.encode()).hexdigest(),
                   "embed": embed}
        config.card_path(name).write_text(json.dumps({
            "word": "needs you", "since": 100, "episode": "e1", "sent": True,
            "open_needs": [pending]}) + "\n")
        config.notify_path(name).with_suffix(".lock").touch()

    def test_a_bash_loop_is_not_listed_and_not_carded(self):
        self.tmux("new-session", "-d", "-s", "chlog-deploy-watch", LOOP)
        self.assertEqual(self.tmux("list-sessions", "-F", "#{session_name}").split(),
                         ["chlog-deploy-watch"])
        self.assertEqual(orch.sessions(), [])
        self.assertNotIn("chlog-deploy-watch", self.listed())
        self.assertIsNone(orch.find("chlog-deploy-watch"))
        notify.tick_cards(log=lambda _: None)
        self.assertFalse(config.card_path("chlog-deploy-watch").exists())
        self.assertEqual(self.requests, [])

    def test_b_a_hand_made_session_running_an_agent_is_a_seat(self):
        self.tmux("new-session", "-d", "-s", "by-hand", str(self.agent()))
        self.tmux("new-session", "-d", "-s", "watcher", LOOP)
        found = self.until_listed("by-hand")
        self.assertIn("by-hand", found)
        self.assertNotIn("watcher", found)
        self.assertFalse(found["by-hand"]["exited"])

    def test_c_an_agentkit_seat_whose_agent_exited_is_still_listed(self):
        self.tmux("new-session", "-d", "-s", "watcher", LOOP)
        self.tmux("set-option", "-g", "remain-on-exit", "on")
        # the two things agentkit's own start leaves on a seat: its mark, and its record
        self.tmux("new-session", "-d", "-s", "marked", "true")
        self.tmux("set-option", "-t", "marked", orch.MARK, "1")
        self.tmux("new-session", "-d", "-s", "recorded", "true")
        config.save_session(self.cfg, "recorded", "fable", ["opus"], {"cwd": str(self.root)})
        deadline = time.monotonic() + 10
        while orch.dead(None) != {"marked", "recorded"} and time.monotonic() < deadline:
            time.sleep(0.05)
        found = self.listed()
        for name in ("marked", "recorded"):
            with self.subTest(seat=name):
                self.assertIn(name, found)
                self.assertTrue(found[name]["exited"])
        self.assertNotIn("watcher", found)

    def test_d_a_gone_sessions_card_is_closed_once_and_goes(self):
        self.tmux("new-session", "-d", "-s", "other-watch", LOOP)
        self.tmux("new-session", "-d", "-s", "chlog-deploy-watch", LOOP)
        self.card("chlog-deploy-watch")
        self.tmux("kill-session", "-t", "=chlog-deploy-watch")
        lines = []
        notify.tick_cards(log=lines.append)
        notify.tick_cards(log=lines.append)
        self.assertEqual(len(self.requests), 1, self.requests)
        method, path, body = self.requests[0]
        self.assertEqual((method, path), ("PATCH", "/api/webhooks/1/token/messages/4242"))
        self.assertEqual(body["embeds"][0]["title"], "Answered · chlog-deploy-watch")
        self.assertNotIn("fields", body["embeds"][0])
        self.assertEqual((body["content"], body["allowed_mentions"]), ("", {"parse": []}))
        self.assertFalse(config.card_path("chlog-deploy-watch").exists())
        # the lock stays: a writer holding or awaiting it would not serialize with a new file
        self.assertTrue(config.notify_path("chlog-deploy-watch").with_suffix(".lock").exists())
        self.assertEqual(lines, ["closed the card of chlog-deploy-watch: no seat holds it any more"])

    def test_e_a_saved_resumable_records_card_is_left_alone(self):
        self.tmux("new-session", "-d", "-s", "other-watch", LOOP)
        config.save_session(self.cfg, "atoll", "fable", ["opus"],
                            {"cwd": str(self.root), "conversation": "c0ffee",
                             "id_source": LAUNCHER})
        self.card("atoll")
        self.assertTrue(self.listed()["atoll"]["resumable"])
        # the ghost row is still the tick's to classify; only the gone-card pass is under test
        with patch.object(notify, "transition") as transition:
            notify.tick_cards(log=lambda _: None)
        self.assertEqual([c.args[0] for c in transition.call_args_list], ["atoll"])
        self.assertEqual(self.requests, [])
        self.assertTrue(config.card_path("atoll").exists())
        self.assertTrue(config.notify_path("atoll").with_suffix(".lock").exists())

    def test_f_a_live_watchers_old_card_is_closed_too(self):
        self.tmux("new-session", "-d", "-s", "chlog-deploy-watch", LOOP)
        self.card("chlog-deploy-watch")   # carded before a watcher stopped being a seat
        notify.tick_cards(log=lambda _: None)
        self.assertEqual([r[0] for r in self.requests], ["PATCH"])
        self.assertFalse(config.card_path("chlog-deploy-watch").exists())
        self.assertEqual(self.tmux("list-sessions", "-F", "#{session_name}").split(),
                         ["chlog-deploy-watch"])   # the session itself is not agentkit's to end

    def test_g_a_harness_by_any_name_is_a_seat_and_a_watcher_naming_one_is_not(self):
        os.mkfifo(self.root / "claude")   # something for `cat` to wait on, with no writer ever
        # Muse's launcher execs its build under the build's own name; an interpreter hands a
        # harness its script past its options; ssh's host is only an argument
        self.tmux("new-session", "-d", "-s", "muse-build", "-c", str(self.root),
                  "bash -c 'exec -a /opt/muse/muse-bin-1.3.0-R1 cat claude'")
        self.tmux("new-session", "-d", "-s", "wrapped", f"bash -e {self.agent()}")
        self.tmux("new-session", "-d", "-s", "ssh-watch", "-c", str(self.root),
                  "bash -c 'exec -a ssh cat claude'")
        pid = self.tmux("display-message", "-p", "-t", "=ssh-watch:", "#{pane_pid}").strip()
        deadline = time.monotonic() + 10
        while (subprocess.run(["ps", "-o", "args=", "-p", pid], capture_output=True,
                              text=True).stdout.strip() != "ssh claude"
               and time.monotonic() < deadline):
            time.sleep(0.05)
        found = self.until_listed("muse-build", "wrapped")
        self.assertIn("muse-build", found)
        self.assertIn("wrapped", found)
        self.assertNotIn("ssh-watch", found)

    def test_h_a_watchers_name_is_taken_before_any_record_or_card_changes(self):
        self.tmux("new-session", "-d", "-s", "chlog-deploy-watch", LOOP)
        self.card("chlog-deploy-watch")
        self.assertIn("chlog-deploy-watch", orch.taken_names())
        starts = {"create": lambda: orch.create(self.cfg, "chlog-deploy-watch", self.root,
                                                selection=({}, ("fable", "", ["opus"]))),
                  "ensure": lambda: orch.ensure(self.cfg, "chlog-deploy-watch")}
        with patch.object(orch.usage, "collect", side_effect=AssertionError("no probe")):
            for how, start in starts.items():
                with self.subTest(start=how), self.assertRaises(config.Error):
                    start()
        self.assertNotIn("chlog-deploy-watch", config.session_records())
        self.assertTrue(config.card_path("chlog-deploy-watch").exists())
        self.assertNotIn("chlog-deploy-watch", self.listed())
        self.assertEqual(self.requests, [])

    def test_i_a_new_seat_under_a_gone_seats_name_closes_its_card_and_a_preview_does_not(self):
        self.card("atoll")
        selection = ({}, ("fable", "", ["opus"]))
        with patch.object(orch, "fresh_command", return_value=(["fake"], None)), \
                patch.object(orch, "launch") as launch, redirect_stdout(io.StringIO()):
            orch.create(self.cfg, "atoll", self.root, selection=selection, dry_run=True)
            self.assertEqual(self.requests, [])            # a preview starts nothing, and
            self.assertTrue(config.card_path("atoll").exists())   # closes nothing either
            orch.create(self.cfg, "atoll", self.root, selection=selection)
        launch.assert_called_once()
        self.assertEqual([(r[0], r[2]["embeds"][0]["title"]) for r in self.requests],
                         [("PATCH", "Answered · atoll")])
        self.assertFalse(config.card_path("atoll").exists())

    def test_j_one_ps_answers_a_whole_tick(self):
        self.tmux("new-session", "-d", "-s", "by-hand", str(self.agent()))
        self.tmux("new-session", "-d", "-s", "chlog-deploy-watch", LOOP)
        self.until_listed("by-hand")
        self.card("chlog-deploy-watch")
        calls, real = [], subprocess.run

        def run(argv, *args, **kwargs):
            if argv[0] == "ps":
                calls.append(argv)
            return real(argv, *args, **kwargs)

        # a reading that goes stale at once: a tick longer than the menu's reuse window
        with patch.object(orch, "AGENT_LOOK_EVERY", 0), \
                patch.object(orch.subprocess, "run", side_effect=run), \
                patch.object(notify, "transition") as transition:
            notify.tick_cards(log=lambda _: None)
        self.assertEqual(len(calls), 1)
        self.assertEqual([c.args[0] for c in transition.call_args_list], ["by-hand"])
        self.assertEqual([r[0] for r in self.requests], ["PATCH"])

    def test_l_an_edit_discord_did_not_take_is_tried_again_on_the_next_tick(self):
        self.tmux("new-session", "-d", "-s", "other-watch", LOOP)
        self.card("gone-seat")
        self.codes = [503]
        lines = []
        notify.tick_cards(log=lines.append)
        card = json.loads(config.card_path("gone-seat").read_text())
        self.assertEqual((card["word"], [n["message_id"] for n in card["open_needs"]]),
                         ("", ["4242"]))
        notify.tick_cards(log=lines.append)
        self.assertEqual([r[0] for r in self.requests], ["PATCH", "PATCH"])
        self.assertFalse(config.card_path("gone-seat").exists())
        self.assertEqual(lines, ["WARN the card of gone-seat was not closed: Discord did not take "
                                 "the edit; retry required",
                                 "closed the card of gone-seat: no seat holds it any more"])

    def test_m_a_record_the_sweep_retires_has_its_card_closed(self):
        config.save_session(self.cfg, "atoll", "fable", ["opus"],
                            {"seen": time.time() - 2 * config.SESSION_STALE})
        self.card("atoll")
        orch.sweep(lambda _: None)
        self.assertNotIn("atoll", config.session_records())
        self.assertEqual([(r[0], r[2]["embeds"][0]["title"]) for r in self.requests],
                         [("PATCH", "Answered · atoll")])
        self.assertFalse(config.card_path("atoll").exists())

    def test_n_a_reused_names_transitions_keep_what_discord_did_not_take(self):
        self.card("atoll")
        self.codes = [503, 503]
        notify.forget_card("atoll")          # the gone seat's close, not taken
        # the new seat's first word closes it again, not taken either; its next one is
        notify.transition("atoll", {"word": "working", "since": time.time(), "reason": "busy"})
        self.assertEqual([n["message_id"] for n in notify._card_read("atoll")["open_needs"]],
                         ["4242"])
        notify.transition("atoll", {"word": "needs you", "since": time.time(), "reason": "ask"})
        self.assertEqual([r[0] for r in self.requests], ["PATCH"] * 3)
        self.assertEqual(notify._card_read("atoll")["open_needs"], [])

    def test_o_a_card_that_is_a_link_is_not_the_sweeps_to_close(self):
        config.save_session(self.cfg, "atoll", "fable", ["opus"],
                            {"seen": time.time() - 2 * config.SESSION_STALE})
        self.card("other")
        config.card_path("atoll").symlink_to(config.card_path("other"))
        orch.sweep(lambda _: None)
        self.assertNotIn("atoll", config.session_records())
        self.assertEqual(self.requests, [])
        self.assertTrue(config.card_path("atoll").is_symlink())
        self.assertTrue(json.loads(config.card_path("other").read_text())["open_needs"])

    def test_k_an_interpreter_runs_its_script_file_and_nothing_else(self):
        cases = {
            # a script file past the interpreter's own options is what runs
            ("bash", "-e", "/opt/bin/claude"): "claude",
            ("bash", "-eo", "pipefail", "/opt/bin/claude"): "claude",
            ("sh", "--", "/opt/bin/claude"): "claude",
            ("python3", "-O", "/opt/bin/claude"): "claude",
            ("python3", "-W", "ignore", "/opt/bin/claude"): "claude",
            ("node", "--require", "/opt/hook/claude", "/opt/app.js"): "app.js",
            ("node", "-r", "claude", "/usr/lib/node_modules/@openai/codex/bin/codex"): "codex",
            ("/opt/muse/muse-bin-1.3.0-R1", "--resume"): "muse-bin-1.3.0-R1",
            # a command string, stdin or a module is no file: the interpreter is what runs
            ("bash", "-c", "claude", "||", "sleep", "600;", "read"): "bash",
            ("bash", "-s", "claude"): "bash",
            ("python3", "-m", "claude"): "python3",
            ("node", "-e", "require('claude')"): "node",
            # and anything else's arguments are only arguments
            ("ssh", "claude", "sleep", "600"): "ssh",
        }
        for words, running in cases.items():
            with self.subTest(command=" ".join(words)):
                self.assertEqual(orch.program(list(words)), running)


if __name__ == "__main__":
    unittest.main()
