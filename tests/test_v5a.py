"""Desktop notices and boot recovery: offline clients, receipts and kernel identities."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import time
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, menu, notify, orch, watch
from agentkit.harness import codex as codex_plugin

REAL_TMUX = shutil.which("tmux")


class DesktopAndBoot(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AGENTKIT_DISCORD_USER_ID": "42", "TMUX_TMPDIR": str(self.root / "sockets")}))
        (self.root / "sockets").mkdir(mode=0o700)
        self.clients = self.root / "clients"
        self.clients.write_text("")
        binaries = self.root / "bin"
        binaries.mkdir()
        fake = binaries / "tmux"
        fake.write_text(f'#!{sys.executable}\nimport os, pathlib, sys\n'
                        'assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv\n'
                        'assert pathlib.Path(os.environ["TMUX_TMPDIR"]).is_dir()\n'
                        'if sys.argv[3] == "list-clients":\n'
                        f'    print(pathlib.Path({str(self.clients)!r}).read_text(), end="")\n'
                        'elif sys.argv[3] != "set-option":\n'
                        '    raise AssertionError(sys.argv)\n')
        fake.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{binaries}:{os.environ['PATH']}"}))
        self.stack.enter_context(patch.object(watch, "boot_id", return_value="fake-boot-new"))
        self.stack.enter_context(patch.object(notify, "session_number", return_value=1))
        self.stack.enter_context(patch.object(orch, "attach", side_effect=AssertionError("attached")))
        self.posts = []
        self.stack.enter_context(patch.object(notify, "post", side_effect=self.post))
        self.stack.enter_context(patch.object(notify, "close_needs", return_value=[]))
        self.seat = {"name": "source", "legacy": False}

    def post(self, payload, files, message, receipt):
        self.posts.append(json.dumps(payload).encode())
        receipt["status"] = "disabled"
        return 0

    def client(self, seat):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        with self.clients.open("a") as fh:
            fh.write(f"{os.ttyname(slave)}\t{seat}\t\t\n")
        return master

    def output(self, fd):
        return os.read(fd, 8192) if select.select([fd], [], [], 0)[0] else b""

    def state(self, live):
        """Put the seat in that live state and read what every screen then says about it."""
        classified = {"state": live, "since": 10000, "began": 10000, "authority": "hook",
                      "rule": "Stop", "evidence": "", "hooked": None, "hooked_at": None}
        with patch.object(watch, "classify", return_value=classified), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text", return_value="fixture"):
            harness, found = watch.look_at(self.seat, cfg=self.cfg)
            return watch.announce_state(self.seat, cfg=self.cfg, live=found,
                                      harness=harness, records=[])["word"]

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for directory in (config.STATE, config.RUNS)
                for p in directory.rglob("*") if p.is_file()}

    def save_seat(self, name, model="fable", **fields):
        config.save_session(self.cfg, name, model, ["opus" if model == "astra" else "astra"],
                            {"cwd": str(self.root), "created": 100, "seen": 9000,
                             "conversation": f"thread-{name}", "id_source": orch.LAUNCHER,
                             **fields})

    def boot_fixture(self):
        state = watch.load_state()
        state["boot_id"] = "fake-boot-old"
        watch.save_state(state)
        self.save_seat("claude")
        self.save_seat("codex", "astra", conversation=None, id_source=None)
        transcript = self.rollout("owned", self.root, "1970-01-01T00:03:00Z", "owned-thread")
        receipt = codex_plugin.prepare("codex", self.root, None)
        codex_plugin.capture(receipt, {"hook_event_name": "SessionStart", "source": "startup",
                                  "session_id": "owned-thread", "transcript_path": str(transcript),
                                  "cwd": str(self.root)})
        self.save_seat("fresh", "astra", conversation="guessed", id_source="discovered")
        self.save_seat("muse", "spark", conversation=None, id_source=None)
        self.save_seat("stopped")
        with redirect_stdout(io.StringIO()):
            orch.cmd_stop(["stopped"])
        # Interrupted work keeps its own receipt and explicit recovery action.
        self.ended("interrupted", state="interrupted", owner="claude")
        self.stack.enter_context(patch.object(orch, "command", side_effect=lambda cfg, model, conversation=None,
            fresh=False: [model, "--session-id" if fresh else "--resume", conversation]))
        self.started = self.stack.enter_context(patch.object(orch, "start"))

    def test_a_asking_notifies_other_client_and_suppresses_active_seat(self):
        active, other = self.client("source"), self.client("other")
        config.hook_facts_path("source").write_text(json.dumps({"event": "Stop", "at": 10000}))
        self.assertEqual(watch.live_state(self.seat, harness="claude", pane="")["state"],
                         "at_prompt")
        self.assertEqual(self.output(other), b"")
        self.assertEqual(self.output(active), b"")
        # The notice goes where the card goes: the other client hears it while
        # the seat's own client stays quiet, which is the suppression above.
        with patch.object(notify, "_attached", return_value=False):
            notify.transition("source", {"word": "needs you", "since": 10000,
                                         "reason": "Which branch?"}, now=10060)
        self.assertEqual(self.output(other),
                         "\033]9;Needs you · source: Which branch?\007".encode())
        self.assertEqual(self.output(active), b"")
        self.assertEqual(len(self.posts), 1)
        self.assertIn("set -g allow-passthrough on", orch.tmux_conf().read_text())

    def test_b_needs_done_shape_and_byte_identical_discord_payload(self):
        active, other = self.client("source"), self.client("menu")
        fixed = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
        working = {"word": "working", "since": 10000, "reason": ""}
        with patch.object(notify, "datetime") as clock, \
                patch.object(notify, "_attached", return_value=False):
            clock.now.return_value = fixed
            for kind, title, text, color, answer in (
                    ("needs", "Needs you", "Which branch?", 0xF5A623,
                     {"word": "needs you", "since": 10000, "reason": "Which branch?"}),
                    ("done", "Done", "Checks passed", 0x2ECC71,
                     {"word": "done", "since": 10100, "reason": "Checks passed"})):
                body = {"title": f"{title} · source", "color": color,
                        "timestamp": "2026-09-14T12:00:00+00:00"}
                # The command records; the card follows the word, once per episode.
                with patch.object(watch, "session_state", return_value=working):
                    self.assertEqual(notify.shaped(kind, text, session="source"), 0)
                self.assertEqual(notify.last("source", include_seen=True)["text"], text)
                notify.transition("source", answer, now=answer["since"] + 60)
                self.assertEqual(self.posts[-1], json.dumps({"username": "agentkit",
                                                             "embeds": [body],
                                                             "content": "<@42>"}).encode())
                self.assertEqual(self.output(other), f"\033]9;{title} · source: {text}\007".encode())
                self.assertEqual(self.output(active), b"")
                notify.transition("source", answer, now=answer["since"] + 120)
                self.assertEqual(self.output(other), b"")
        self.assertEqual(len(self.posts), 2)
        before = self.snapshot()
        notify.retry_pending()
        self.assertEqual(self.output(other), b"")
        self.assertEqual(self.snapshot(), before)

    def test_c_no_client_sends_nothing_and_records_no_terminal_delivery(self):
        before = self.snapshot()
        self.assertFalse(notify.terminal_notice("source", "source · needs you"))
        self.assertEqual(self.snapshot(), before)
        self.state("asking")
        self.assertNotIn("terminal_notices", watch.seat_read("source"))
        self.assertFalse(notify.outbox().exists())
        # Configured Discord behavior remains independent of desktop presence.
        notify.shaped("needs", "Which branch?", session="source")
        self.assertEqual(len(self.posts), 1)
        event = json.loads(next(notify.outbox().glob("*.json")).read_text())
        self.assertEqual(event["attempts"], 1)
        self.assertNotIn("terminal", json.dumps(event))

    def test_d_same_episode_toasts_once_and_a_new_episode_toasts_again(self):
        other = self.client("other")
        held = {"word": "needs you", "since": 10000, "reason": "Which branch?"}
        resting = {"word": "working", "since": 10100, "reason": ""}
        with patch.object(notify, "_attached", return_value=False):
            notify.transition("source", held, now=10060)      # tells
            notify.transition("source", held, now=10120)      # same episode: quiet
            notify.transition("source", resting, now=10120)
            notify.transition("source", held, now=10180)      # new episode: tells again
        self.assertEqual(self.output(other).count(b"\033]9;"), 2)

    def test_e_changed_boot_resumes_only_proven_records_once(self):
        self.boot_fixture()
        fresh = config.session_path("fresh").read_bytes()
        interrupted = self.snapshot()["runs/interrupted/run.json"]
        logs = []
        watch.resume_after_boot(self.cfg, log=logs.append)
        self.assertEqual([call.args[0] for call in self.started.call_args_list], ["claude", "codex"])
        for call in self.started.call_args_list:
            self.assertEqual(call.args[1], self.root)
        claude, codex = self.started.call_args_list
        self.assertIn("thread-claude", claude.args[2])
        self.assertIn("owned-thread", codex.args[2])
        self.assertEqual(config.session_records()["claude"]["seen"], 9000)
        self.assertEqual(config.session_path("fresh").read_bytes(), fresh)
        self.assertFalse(config.session_path("stopped").exists())
        self.assertEqual(self.snapshot()["runs/interrupted/run.json"], interrupted)
        self.assertEqual(logs, ["resumed claude after reboot", "resumed codex after reboot"])
        self.assertEqual(watch.load_state()["boot_id"], "fake-boot-new")
        before = self.snapshot()
        watch.resume_after_boot(self.cfg, log=logs.append)
        self.assertEqual(self.started.call_count, 2)
        self.assertEqual(self.snapshot(), before)

    def test_f_watch_dry_run_names_resumes_and_changes_no_state(self):
        self.boot_fixture()
        # Even stale babysitter entries must not reconcile unrelated unowned records.
        state = watch.load_state()
        state["stalls"]["fresh"] = {}
        watch.save_state(state)
        self.save_seat("unowned-claude", conversation="guessed", id_source="discovered")
        before = self.snapshot()
        with patch.object(watch, "gh_json", return_value=({"login": "fixture"}, "")), \
                patch.object(watch, "incoming"), patch.object(watch, "outgoing"), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(watch.main(["--dry-run"]), 0)
        self.assertIn("would resume claude after reboot", out.getvalue())
        self.assertIn("would resume codex after reboot", out.getvalue())
        for name in ("fresh", "muse", "stopped", "interrupted"):
            self.assertNotIn(f"would resume {name}", out.getvalue())
        self.started.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_worker_silence_sanitization_and_notify_preview(self):
        other = self.client("other")
        with patch.dict(os.environ, {"AK_RUN_ROLE": "worker"}), redirect_stdout(io.StringIO()):
            self.state("asking")
            notify.shaped("needs", "Question?", session="source")
        self.assertEqual(self.output(other), b"")
        self.assertFalse(self.posts)
        before = self.snapshot()
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            notify.main(["needs", "Question?", "--session", "source", "--dry-run"])
        self.assertEqual(json.loads(out.getvalue())["embeds"][0]["title"], "Needs you · source")
        self.assertNotIn("description", json.loads(out.getvalue())["embeds"][0])
        self.assertIn("terminal notice: Needs you · source: Question?", err.getvalue())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.output(other), b"")
        notify.terminal_notice("source", "Question?\007\033]52;bad\nnext")
        self.assertEqual(self.output(other), b"\033]9;Question? ]52;bad next\007")

    def test_concurrent_recovery_failure_claim_and_stale_watch_save(self):
        self.boot_fixture()
        stale = watch.load_state()
        with patch.object(orch, "resume", side_effect=config.Error("fixture launch failed")) as resume:
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _: watch.resume_after_boot(self.cfg, log=lambda _: None), range(2)))
            self.assertEqual(resume.call_count, 2)
        watch.save_state(stale)
        self.assertEqual(watch.load_state()["boot_id"], "fake-boot-new")
        with patch.object(orch, "resume") as resume:
            watch.resume_after_boot(self.cfg)
            resume.assert_not_called()

    def test_killed_recovery_continues_unclaimed_seats_and_next_boot_is_independent(self):
        self.boot_fixture()
        with patch.object(orch, "resume", side_effect=KeyboardInterrupt) as resume:
            with self.assertRaises(KeyboardInterrupt):
                watch.resume_after_boot(self.cfg)
            self.assertEqual(resume.call_args.args[1], "claude")
        self.assertEqual(watch.load_state()["boot_id"], "fake-boot-old")
        with patch.object(orch, "resume", return_value=0) as resume:
            watch.resume_after_boot(self.cfg, log=lambda _: None)
            self.assertEqual([call.args[1] for call in resume.call_args_list], ["codex"])
            with patch.object(watch, "boot_id", return_value="fake-boot-next"):
                watch.resume_after_boot(self.cfg, log=lambda _: None)
                watch.resume_after_boot(self.cfg, log=lambda _: None)
            self.assertEqual([call.args[1] for call in resume.call_args_list], ["codex", "claude", "codex"])

    def test_terminal_failure_and_discord_retry_never_retry_the_toast(self):
        other = self.client("other")
        with patch.object(notify, "post", side_effect=lambda *args: args[-1].update(status="pending")), \
                redirect_stderr(io.StringIO()):
            notify.shaped("needs", "Question?", session="source")
        self.assertEqual(self.output(other).count(b"\033]9;"), 1)
        with patch.object(notify.time, "time", return_value=10100):
            notify.retry_pending()
        self.assertEqual(self.output(other), b"")
        self.assertEqual(len(self.posts), 1)
        # A disconnected client does not prevent Discord's next event.
        with patch.object(notify.os, "write", side_effect=OSError("gone")):
            self.assertEqual(notify.shaped("done", "Finished", session="source"), 0)
        self.assertEqual(len(self.posts), 2)

    def test_dead_pane_with_recycled_tty_notifies_each_client_and_never_the_old_tty(self):
        active, first, second, recycled = (self.client(name) for name in
                                           ("source", "other", "other", "unrelated"))
        ttys = [line.split("\t")[0] for line in self.clients.read_text().splitlines()]
        self.clients.write_text(f"{ttys[0]}\tsource\t@0\t\t0\n"
                                f"{ttys[1]}\tother\t@1\t{ttys[3]}\t1\n"
                                f"{ttys[2]}\tother\t@1\t{ttys[3]}\t1\n")
        self.assertEqual(notify.terminal_targets("source"), [(ttys[1], False), (ttys[2], False)])
        with patch.object(notify, "_attached", return_value=False):
            notify.transition("source", {"word": "needs you", "since": 10000,
                                         "reason": "Which branch?"}, now=10060)
        for client in (first, second):
            self.assertEqual(self.output(client),
                             "\033]9;Needs you · source: Which branch?\007".encode())
        for client in (active, recycled):
            self.assertEqual(self.output(client), b"")

    def test_short_terminal_writes_are_not_counted_or_retried(self):
        self.client("other")
        for count in (0, 5):
            with self.subTest(count=count), patch.object(notify.os, "write", return_value=count) as write:
                self.assertFalse(notify.terminal_notice("source", "source · needs you"))
                write.assert_called_once()
                self.assertFalse(notify.terminal_notice("source", "source · needs you"))
                self.assertEqual(write.call_count, 2)
                self.assertNotIn("terminal_notices", watch.seat_read("source"))
        self.assertFalse(notify.outbox().exists())
        self.client("another")
        with patch.object(notify.os, "write", side_effect=lambda fd, data:
                          len(data) if write.call_count == 1 else 0) as write:
            self.assertTrue(notify.terminal_notice("source", "source · needs you"))
            self.assertEqual(write.call_count, 2)

    def test_menu_reports_each_recovered_seat_once_before_maintenance(self):
        self.boot_fixture()
        with patch.object(config, "server_alias", return_value=None), \
                patch("agentkit.macbridge.start_background"), patch.object(menu, "loop", return_value=0), \
                patch.object(menu, "show_notices") as notices:
            menu.main(["--overlay"])
            self.assertEqual(notices.call_args.args[0],
                             ["resumed claude after reboot", "resumed codex after reboot"])
            menu.main(["--overlay"])
            self.assertEqual(notices.call_args.args[0], [])
        self.assertEqual(self.started.call_count, 2)

    def test_missing_boot_id_baseline_and_missing_directory_never_start_fresh(self):
        self.save_seat("old")
        with patch.object(orch, "resume") as resume:
            watch.resume_after_boot(self.cfg)
            resume.assert_not_called()
        self.assertEqual(watch.load_state()["boot_id"], "fake-boot-new")
        self.save_seat("missing", cwd=str(self.root / "gone"))
        with self.assertRaisesRegex(config.Error, "recorded directory"):
            orch.resume(self.cfg, "missing", detached=True)
        with patch.object(watch, "boot_id", return_value=None):
            before = self.snapshot()
            watch.resume_after_boot(self.cfg)
            self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(REAL_TMUX, "requires tmux")
    def test_real_isolated_tmux_passthrough_and_shared_window_active_suppression(self):
        argv = [REAL_TMUX, "-L", "agentkit-test", "-S", "agentkit-test"]
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        env.update(TERM="xterm-256color", LC_ALL="C.UTF-8")

        def tmux(*args):
            result = subprocess.run([*argv, *args], cwd=self.root, env=env,
                                    capture_output=True, text=True, timeout=10)
            return result.returncode, (result.stdout + result.stderr).strip()

        self.assertEqual(tmux("-f", "/dev/null", "new-session", "-d", "-s", "source",
                              "-x", "80", "-y", "24", "sleep", "60")[0], 0)
        self.addCleanup(tmux, "kill-server")
        self.assertEqual(tmux("new-session", "-d", "-s", "other", "sleep", "60")[0], 0)
        masters = []
        for name in ("source", "other", "other"):
            master, slave = pty.openpty()
            self.addCleanup(os.close, master)
            self.addCleanup(os.close, slave)
            proc = subprocess.Popen([*argv, "attach-session", "-t", f"={name}"],
                                    cwd=self.root, env=env, stdin=slave, stdout=slave, stderr=slave)
            self.addCleanup(proc.wait, 10)
            self.addCleanup(proc.terminate)
            masters.append(master)

        deadline = time.monotonic() + 5
        while len(tmux("list-clients", "-F", "#{client_tty}")[1].splitlines()) < 3:
            self.assertLess(time.monotonic(), deadline, "fake terminal clients did not attach")
            time.sleep(0.02)

        def collect():
            found = [bytearray() for _ in masters]
            until = time.monotonic() + 0.3
            while time.monotonic() < until:
                ready = select.select(masters, [], [], 0.02)[0]
                for fd in ready:
                    found[masters.index(fd)] += os.read(fd, 65536)
            return [bytes(blob) for blob in found]

        with patch.object(orch, "tmux_out", side_effect=lambda *args, **kw: tmux(*args)):
            collect()
            self.assertTrue(notify.terminal_notice("source", "source · needs you"))
            received = collect()
            self.assertNotIn(b"\033]9;", received[0])
            for output in received[1:]:
                self.assertEqual(output.count("\033]9;source · needs you\007".encode()), 1, output)
                self.assertNotIn(b"\033Ptmux;", output)
            recipient = tmux("list-clients", "-F", "#{client_tty}\t#{session_name}")[1]
            tty = next(line.split("\t")[0] for line in recipient.splitlines() if line.endswith("\tother"))
            popup = subprocess.Popen([*argv, "display-popup", "-c", tty, "-E", "sleep 60"],
                                     cwd=self.root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(popup.wait, 10)
            self.addCleanup(popup.terminate)
            collect()
            self.assertTrue(notify.terminal_notice("source", "Menu notice"))
            received = collect()
            for output in received[1:]:
                self.assertEqual(output.count(b"\033]9;Menu notice\007"), 1, output)
            self.assertEqual(tmux("display-popup", "-C", "-c", tty)[0], 0)
            popup.wait(timeout=5)
            # Share the recipient's window with the source: a pane broadcast would now
            # reach the active seat as well. Only the other two client ttys may receive it.
            self.assertEqual(tmux("link-window", "-s", "=other:0", "-t", "=source:1")[0], 0)
            self.assertEqual(tmux("select-window", "-t", "=source:1")[0], 0)
            collect()
            self.assertTrue(notify.terminal_notice("source", "source · needs you"))
            received = collect()
            self.assertNotIn(b"\033]9;", received[0])
            for output in received[1:]:
                self.assertEqual(output.count("\033]9;source · needs you\007".encode()), 1, output)
            # A normal exited seat is still attached, but its old pane tty is no longer
            # owned. With the source back in its own window, both other clients still hear it.
            self.assertEqual(tmux("select-window", "-t", "=source:0")[0], 0)
            self.assertEqual(tmux("unlink-window", "-t", "=source:1")[0], 0)
            self.assertEqual(tmux("set-option", "-g", "remain-on-exit", "on")[0], 0)
            self.assertEqual(tmux("respawn-pane", "-k", "-t", "=other:0", "true")[0], 0)
            deadline = time.monotonic() + 5
            while tmux("display-message", "-p", "-t", "=other:0", "#{pane_dead}")[1] != "1":
                self.assertLess(time.monotonic(), deadline, "fixture pane did not exit")
                time.sleep(0.02)
            collect()
            self.assertTrue(notify.terminal_notice("source", "Notice after exit"))
            received = collect()
            self.assertNotIn(b"\033]9;", received[0])
            for output in received[1:]:
                self.assertEqual(output.count(b"\033]9;Notice after exit\007"), 1, output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
