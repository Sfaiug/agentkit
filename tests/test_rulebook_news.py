"""A seat open across a rulebook change is told with its next prompt, through its prompt hook.

Offline: a temporary HOME, real seat records and the real hooks/seat-state.sh, outside tmux.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, notify, orch, statusbar, watch
from agentkit.harness import codex

SEAT = "acme-fix"
BEFORE = "the rules from before\n"
OWN = "0f5d6e2a-6a43-4c3e-9b0e-3a1f6c2d9e10"      # the conversation the seat's launch handed out
OWNED = {"conversation": OWN, "id_source": "launcher", "resumable": True}


class RulebookNews(Sandbox):
    def setUp(self):
        super().setUp()
        # the hook's own process and these readers share one HOME
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root), **OWNED})

    def handed(self, text, name=SEAT, recorded=True):
        """The rulebook a launch under `name` handed the seat."""
        config.rulebook_path(name).write_text(text)
        if recorded:
            config.update_session(config.resolve_session(name),
                                  rulebook_sha=config.rulebook_digest(text))

    def prompt(self, event="UserPromptSubmit", session=SEAT, conversation=OWN, **env):
        result = subprocess.run(
            ["bash", str(REPO / "hooks/seat-state.sh")],
            input=json.dumps({"hook_event_name": event, "prompt": "carry on",
                              "session_id": conversation}),
            text=True, capture_output=True, timeout=30,
            env={"HOME": str(self.root), "PATH": os.environ["PATH"],
                 "AGENTKIT_SESSION": session, "AK_RUN_ROLE": "orchestrator", **env})
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return result.stdout

    def said_read(self, notice, session=SEAT):
        """The seat runs the `ak orch rules DIGEST` its notice gave."""
        digest = re.search(r"ak orch rules ([0-9a-f]+)", notice).group(1)
        with patch.dict(os.environ, {config.SESSION_ENV: session}), \
                patch("sys.stdout", new_callable=lambda: open(os.devnull, "w")):
            return orch.cmd_rules([digest])

    def test_a_changed_rulebook_is_named_in_every_prompt_until_the_seat_says_it_read_it(self):
        self.handed(BEFORE)
        told = json.loads(self.prompt())["hookSpecificOutput"]
        path = config.rulebook_path(SEAT)
        self.assertEqual(told["hookEventName"], "UserPromptSubmit")
        self.assertIn(f"Read {path} in full", told["additionalContext"])
        self.assertEqual(path.read_text(), config.seat_rulebook(SEAT))
        self.assertIn("has changed", self.prompt())   # not said read yet: told again
        self.assertEqual(self.said_read(told["additionalContext"]), 0)
        self.assertEqual(config.session_records()[SEAT]["rulebook_read"],
                         {"conversation": OWN, "sha": config.rulebook_digest(config.seat_rulebook(SEAT))})
        self.assertEqual(self.prompt(), "")

    def test_a_rulebook_said_read_after_it_changed_again_is_read_again(self):
        rules = config.HOME / "rules.md"
        rules.write_text("Rule one.\n")
        self.handed(config.seat_rulebook(SEAT))
        rules.write_text("Rule two.\n")
        notice = self.prompt()
        rules.write_text("Rule three.\n")
        self.assertIn("has changed", self.prompt())       # the file now says rule three
        with self.assertRaisesRegex(config.Error, "not the code the seat's latest prompt gave"):
            self.said_read(notice)
        self.assertIn("has changed", self.prompt())

    def test_a_conversation_clear_started_is_told_again(self):
        # /clear keeps the harness and its launch rulebook, and drops what the old one read
        self.handed(BEFORE)
        self.said_read(self.prompt())
        cleared = "c3a1f2e4-5b6d-4e7f-8a9b-0c1d2e3f4a5b"
        config.update_session(SEAT, conversation=cleared, id_source="claude-hook")
        notice = self.prompt(conversation=cleared)
        self.assertIn("has changed", notice)
        self.said_read(notice)
        self.assertEqual(self.prompt(conversation=cleared), "")

    def test_a_prompt_refused_before_its_turn_offers_it_again(self):
        self.handed(BEFORE)
        self.assertIn("has changed", self.prompt())
        # another hook refused that prompt: nothing said it was read
        self.said_read(self.prompt())
        self.assertEqual(self.prompt(), "")

    def test_rules_restored_before_an_offer_was_read_are_offered_again(self):
        rules = config.HOME / "rules.md"
        rules.write_text("Rule one.\n")
        self.handed(config.seat_rulebook(SEAT))          # opened on rule one
        rules.write_text("Rule two.\n")
        self.assertIn("has changed", self.prompt())      # rule two offered; no turn ran on it
        rules.write_text("Rule one.\n")                  # the owner put rule one back
        notice = self.prompt()                            # the file it was told says rule two
        self.assertIn("has changed", notice)
        self.assertIn("Rule one.", config.rulebook_path(SEAT).read_text())
        self.said_read(notice)
        self.assertEqual(self.prompt(), "")

    def test_a_prompt_typed_while_the_seat_is_held_tells_the_file_as_it_stands(self):
        self.handed(BEFORE)
        self.assertIn("has changed", self.prompt())     # told; another hook refused it
        with notify.session_lock(SEAT):                  # the next prompt, typed by a delivery
            notice = self.prompt()
        self.assertIn("has changed", notice)
        self.said_read(notice)
        self.assertEqual(self.prompt(), "")

    def test_a_nested_client_neither_hears_nor_reads_the_seat_s_notice(self):
        self.handed(BEFORE)
        self.assertIn("has changed", self.prompt())     # offered; another hook refused it
        self.assertEqual(self.prompt(conversation="acme-nested"), "")
        self.assertIn("has changed", self.prompt())

    def test_a_conversation_its_harness_does_not_vouch_for_is_never_told(self):
        # an id the record holds without the launcher's or the harness's own word for it
        self.handed(BEFORE)
        config.update_session(SEAT, id_source="discovered", resumable=False)
        self.assertEqual(self.prompt(), "")
        self.assertEqual(config.rulebook_path(SEAT).read_text(), BEFORE)

    def test_only_a_conversation_its_harness_vouches_for_says_it_read_it(self):
        self.handed(BEFORE)
        notice = self.prompt()
        config.update_session(SEAT, id_source="discovered", resumable=False)
        with self.assertRaisesRegex(config.Error, "not the one that code was given to"):
            self.said_read(notice)
        self.assertNotIn("rulebook_read", config.session_records()[SEAT])

    def test_a_client_started_inside_the_seat_is_never_told(self):
        # it inherits the seat's name; its conversation is its own, never the seat's
        self.handed(BEFORE)
        nested = "7c1e0a55-2b7d-4f0e-8a51-5d8b1f4c3a22"
        self.assertEqual(self.prompt(conversation=nested), "")
        self.assertEqual(self.prompt("Stop", conversation=nested), "")
        self.assertEqual(config.rulebook_path(SEAT).read_text(), BEFORE)
        self.assertIn("has changed", self.prompt())

    def test_a_current_rulebook_or_none_ever_handed_says_nothing(self):
        self.assertEqual(self.prompt(), "")      # no launch of ours handed it one
        self.handed(config.seat_rulebook(SEAT))
        self.assertEqual(self.prompt(), "")

    def test_a_seat_launched_before_the_record_kept_it_is_told_from_its_file(self):
        self.handed(BEFORE, recorded=False)
        self.assertIn("has changed", self.prompt())

    def test_a_record_write_that_fails_leaves_an_old_seats_rulebook_to_offer_again(self):
        self.handed(BEFORE, recorded=False)      # its file is its only word on its launch
        blocked = config.session_path(SEAT).with_suffix(".tmp")
        blocked.mkdir()                          # the record cannot be written for now
        self.assertEqual(self.prompt(), "")
        self.assertEqual(config.rulebook_path(SEAT).read_text(), BEFORE)
        blocked.rmdir()
        self.assertIn("has changed", self.prompt())

    def test_a_rewrite_that_fails_names_nothing_and_the_next_prompt_does(self):
        self.handed(BEFORE)
        replace = Path.replace

        def full(path, target):
            if Path(target).name.startswith("rulebook-"):
                raise OSError("disk full")       # the rulebook file alone cannot be written
            return replace(path, target)

        with patch.object(Path, "replace", full):
            self.assertEqual(orch.rulebook_news(SEAT, OWN), "")   # nothing to read, so no news
        self.assertEqual(config.rulebook_path(SEAT).read_text(), BEFORE)
        self.assertIn("has changed", self.prompt())

    def test_a_turn_whose_prompt_carried_nothing_says_nothing_read(self):
        rules = config.HOME / "rules.md"
        rules.write_text("Rule one.\n")
        self.handed(config.seat_rulebook(SEAT))
        rules.write_text("Rule two.\n")
        self.assertIn("has changed", self.prompt())      # told; another hook refused it
        rules.write_text("Rule three.\n")
        replace = Path.replace

        def full(path, target):
            if Path(target).name.startswith("rulebook-"):
                raise OSError("disk full")
            return replace(path, target)

        with patch.object(Path, "replace", full):
            self.assertEqual(orch.rulebook_news(SEAT, OWN), "")   # its rewrite failed
        self.prompt("Stop")                                  # and its turn ran without it
        self.assertNotIn("rulebook_read", config.session_records()[SEAT])
        self.assertIn("has changed", self.prompt())

    def test_a_client_that_inherited_the_seat_s_name_cannot_say_it_read_anything(self):
        self.handed(BEFORE)
        self.prompt()                                     # the seat's own prompt is told
        self.assertEqual(self.prompt(conversation="acme-nested"), "")
        digest = config.rulebook_digest(config.rulebook_path(SEAT).read_bytes())
        with self.assertRaisesRegex(config.Error, "not the code"):
            self.said_read(f"ak orch rules {digest[:12]}")   # the file's digest is no code
        self.assertNotIn("rulebook_read", config.session_records()[SEAT])

    def test_rules_that_changed_since_the_notice_are_not_said_read(self):
        rules = config.HOME / "rules.md"
        rules.write_text("Rule one.\n")
        self.handed(config.seat_rulebook(SEAT))
        rules.write_text("Rule two.\n")
        notice = self.prompt()
        rules.write_text("Rule three.\n")               # no prompt since
        with self.assertRaisesRegex(config.Error, "rules changed since that prompt"):
            self.said_read(notice)
        self.assertNotIn("rulebook_read", config.session_records()[SEAT])
        self.assertIn("has changed", self.prompt())

    def test_a_launch_recorded_while_a_prompt_waits_keeps_its_rulebook(self):
        self.handed(BEFORE)
        newer = config.rulebook_digest("a newer launch's rules\n")
        lock = notify.session_lock

        @contextmanager
        def launched_meanwhile(name, *args, **kwargs):
            # a newer launch records what it handed between this prompt's read and its lock
            config.update_session(SEAT, rulebook_sha=newer)
            with lock(name, *args, **kwargs) as current:
                yield current

        with patch.object(notify, "session_lock", side_effect=launched_meanwhile):
            orch.rulebook_news(SEAT, OWN)
        self.assertEqual(config.session_records()[SEAT]["rulebook_sha"], newer)

    def test_rules_put_back_stay_told_until_the_seat_says_it_read_them(self):
        rules = config.HOME / "rules.md"
        rules.write_text("Rule one.\n")
        self.handed(config.seat_rulebook(SEAT))          # launched on rule one
        rules.write_text("Rule two.\n")
        self.assertIn("has changed", self.prompt())      # told rule two, never said read
        rules.write_text("Rule one.\n")
        self.assertIn("has changed", self.prompt())      # told it is back; another hook refused
        notice = self.prompt()
        self.assertIn("has changed", notice)             # so the next prompt tells it again
        self.said_read(notice)
        self.assertEqual(self.prompt(), "")

    def test_a_missing_rulebook_file_is_written_again_and_told(self):
        self.handed(BEFORE)
        config.rulebook_path(SEAT).unlink()
        self.assertIn("has changed", self.prompt())
        self.assertEqual(config.rulebook_path(SEAT).read_text(), config.seat_rulebook(SEAT))

    def test_a_launch_records_the_file_as_it_reads_under_the_seat_s_lock(self):
        config.rulebook_path(SEAT).write_text(BEFORE)
        lock = notify.session_lock

        @contextmanager
        def rewritten_first(name, *args, **kwargs):
            # a prompt of the conversation still running rewrites it just before
            config.rulebook_path(SEAT).write_text("the newer rules\n")
            with lock(name, *args, **kwargs) as current:
                yield current

        with patch.object(notify, "session_lock", side_effect=rewritten_first), \
                patch.object(orch, "start"), patch.object(statusbar, "dress"):
            orch.launch(SEAT, "opus", str(self.root), ["true"], OWN)
        self.assertEqual(config.session_records()[SEAT]["rulebook_sha"],
                         config.rulebook_digest("the newer rules\n"))

    def test_the_harness_a_launch_replaces_never_rewrites_what_it_recorded(self):
        config.rulebook_path(SEAT).write_text(config.seat_rulebook(SEAT))   # what it hands
        told = []

        def starting(*_args, **_kwargs):
            # the rules change and the old harness, still in its pane, prompts before it goes
            (config.HOME / "rules.md").write_text("A newer rule.\n")
            told.append(orch.rulebook_news(SEAT, OWN))

        with patch.object(orch, "_start_harness", side_effect=starting):
            orch.launch(SEAT, "opus", str(self.root), ["true"], OWN)
        self.assertEqual(config.session_records()[SEAT]["rulebook_sha"],
                         config.rulebook_digest(config.rulebook_path(SEAT).read_bytes()))
        self.assertNotIn("A newer rule.", config.rulebook_path(SEAT).read_text())
        self.assertIn("has changed", self.prompt())     # the new harness is told after

    def test_only_a_seats_prompt_hears_it(self):
        self.handed(BEFORE)
        for event, env in (("Stop", {}), ("Notification", {}),
                           ("UserPromptSubmit", {"AK_RUN_ROLE": "worker"}),
                           ("UserPromptSubmit", {"AGENTKIT_SESSION": ""})):
            with self.subTest(event=event, env=env):
                self.assertEqual(self.prompt(event, **env), "")
        self.assertEqual(config.rulebook_path(SEAT).read_text(), BEFORE)

    def test_a_harness_whose_prompt_takes_no_context_reads_it_at_its_next_launch(self):
        config.save_session(self.cfg, SEAT, "mimo", ["mimo"], {"cwd": str(self.root), **OWNED})
        self.assertFalse(orch.seat_plugin(config.session_records()[SEAT]).prompt_context)
        self.handed(BEFORE)
        self.assertEqual(self.prompt(), "")
        self.assertEqual(config.rulebook_path(SEAT).read_text(), BEFORE)

    def test_a_renamed_seat_is_told_through_the_name_it_was_launched_under(self):
        config.save_session(self.cfg, "acme-old", "opus", ["astra"], {"cwd": str(self.root), **OWNED})
        self.handed(BEFORE, name="acme-old", recorded=False)
        config.rename_session("acme-old", "acme-new")
        told = json.loads(self.prompt(session="acme-old"))["hookSpecificOutput"]
        self.assertIn(str(config.rulebook_path("acme-old")), told["additionalContext"])
        self.said_read(told["additionalContext"], session="acme-old")
        self.assertEqual(config.session_records()["acme-new"]["rulebook_read"],
                         {"conversation": OWN,
                          "sha": config.rulebook_digest(config.seat_rulebook("acme-new"))})

    def test_a_codex_seat_is_told_through_the_conversation_its_receipt_proves(self):
        thread, cwd = "acme-thread", str(self.root)
        rollout = self.root / ".codex/rollout.jsonl"
        rollout.parent.mkdir()
        rollout.write_text(json.dumps({"type": "session_meta",
                                       "payload": {"id": thread, "cwd": cwd}}) + "\n")
        token = "a" * 32
        config.save_session(self.cfg, SEAT, "astra", ["opus"], {
            "cwd": cwd, "conversation": thread, "id_source": codex.SOURCE,
            "codex_launch": token, "resumable": True})
        codex.path_for({"codex_launch": token}).write_text(json.dumps({
            "launch": token, "cwd": cwd, "expected": thread, "event": {
                "hook_event_name": "SessionStart", "source": "startup", "session_id": thread,
                "cwd": cwd, "transcript_path": str(rollout)}}))
        self.handed(BEFORE)
        self.assertEqual(self.prompt(conversation="acme-nested-thread"), "")
        self.assertIn("has changed", self.prompt(conversation=thread))

    def test_a_prompt_never_waits_on_a_delivery_holding_the_seat(self):
        self.handed(BEFORE)
        with notify.session_lock(SEAT):        # a delivery typing this very prompt
            self.assertEqual(self.prompt(), "")
        self.assertEqual(config.rulebook_path(SEAT).read_text(), BEFORE)
        self.assertIn("has changed", self.prompt())

    def test_a_prompt_delivered_under_the_seat_s_lock_is_told(self):
        # an autonomous seat's prompts are ak's deliveries, each typed under the seat's lock
        self.handed(BEFORE)
        heard = []

        def tmux(*args, **_kw):
            if args[:1] == ("send-keys",) and args[-1] == "Enter":
                heard.append(self.prompt())     # the hook runs as the Enter lands, lock held
            return 0, ""

        with patch.object(watch, "_send_line", return_value=True), \
                patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(watch, "pane_text", return_value=""), \
                patch.object(watch, "KEY_GAP", 0):
            self.assertTrue(watch.type_into({"name": SEAT}, "a peer note", lambda _line: None))
        self.assertIn("has changed", heard[0])
        self.assertEqual(config.rulebook_path(SEAT).read_text(), config.seat_rulebook(SEAT))

    def test_a_delivery_s_retried_enter_is_told(self):
        # an Enter that failed left the line typed; the rules change before the retry
        self.handed(BEFORE)
        heard, line = [], "a peer note"

        def tmux(*args, **_kw):
            if args[:1] == ("send-keys",) and args[-1] == "Enter":
                heard.append(self.prompt())
            return 0, ""

        with patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(watch, "seat_model", return_value=("claude", "opus")), \
                patch.object(watch, "pane_text", return_value=f"> {line}"), \
                patch.object(watch, "_holds_text", return_value=True), \
                patch.object(watch, "asking", return_value=False):
            watch.type_at_prompt({"name": SEAT}, line, lambda _line: None, cfg=self.cfg,
                                 typed={"line": line, "seat": None})
        self.assertIn("has changed", heard[0])

    def test_a_renamed_seat_from_before_keeps_its_file_through_a_failed_relaunch(self):
        config.save_session(self.cfg, "acme-old", "opus", ["astra"], {"cwd": str(self.root), **OWNED})
        self.handed(BEFORE, name="acme-old", recorded=False)
        config.rename_session("acme-old", "acme-new")
        orch.keep_launch_rulebook("acme-new")      # before the relaunch's adapter writes
        time.sleep(0.05)
        config.rulebook_path("acme-new").write_text("the relaunch's, never read\n")
        (config.HOME / "rules.md").write_text("A newer rule.\n")
        with notify.session_lock("acme-new") as held:   # the relaunch failed; a delivery types
            orch.rulebook_prepare(held)
            told = self.prompt(session="acme-old")
        self.assertIn(str(config.rulebook_path("acme-old")), told)
        self.assertEqual(config.rulebook_path("acme-old").read_text(),
                         config.seat_rulebook("acme-new"))

    def test_a_rulebook_file_cut_mid_character_is_written_again(self):
        self.handed(BEFORE)
        config.rulebook_path(SEAT).write_bytes("Rule two \u2013".encode()[:-1])   # a failed write
        self.assertIn("has changed", self.prompt())
        self.assertEqual(config.rulebook_path(SEAT).read_text(), config.seat_rulebook(SEAT))

    def test_its_record_writes_never_land_over_a_rename(self):
        # while a rename holds the seat's lock: a prompt skips, a launch waits, neither writes
        for writer in ("prompt", "launch"):
            with self.subTest(writer=writer):
                seat = f"acme-{writer}"
                config.save_session(self.cfg, seat, "opus", ["astra"],
                                    {"cwd": str(self.root), **OWNED})
                self.handed(BEFORE, name=seat)
                if writer == "launch":
                    config.rulebook_path(seat).write_text(config.seat_rulebook(seat))
                stale, write = config.session_path(seat), config._write_json
                reached = threading.Event()

                def paused(path, data, *args, **kw):
                    if path == stale and data.get("rulebook_sha") != config.rulebook_digest(BEFORE):
                        reached.set()
                    return write(path, data, *args, **kw)

                def update():
                    if writer == "prompt":
                        orch.rulebook_news(seat, OWN)
                    else:
                        orch.launch(seat, "opus", str(self.root), ["true"], None)

                with patch.object(config, "_write_json", side_effect=paused), \
                        patch.object(orch, "start"), patch.object(statusbar, "dress"):
                    with notify.session_lock(seat):
                        thread = threading.Thread(target=update)
                        thread.start()
                        # a writer that took the lock waits here; one that did not writes
                        self.assertFalse(reached.wait(1))
                        config.rename_session(seat, f"{seat}-renamed")
                    thread.join(10)
                self.assertEqual(config.resolve_session(seat), f"{seat}-renamed")
                self.assertNotIn(seat, config.session_records())

    def test_writers_of_other_fields_never_undo_a_read(self):
        # `orch.stamp` writes `seen` from a read made before the prompt's offer
        read, held = config._read_json, threading.Event()

        def slow(path):
            data = read(path)
            if threading.current_thread().name == "stamp" and path == config.session_path(SEAT):
                held.set()
                time.sleep(0.3)
            return data

        with patch.object(config, "_read_json", side_effect=slow):
            stamp = threading.Thread(target=config.update_session, args=(SEAT,),
                                     kwargs={"seen": 1}, name="stamp")
            stamp.start()
            held.wait(5)
            config.update_session(SEAT, rulebook_read="the one read")
            stamp.join(5)
        record = config.session_records()[SEAT]
        self.assertEqual((record["seen"], record["rulebook_read"]), (1, "the one read"))

    def test_rules_that_change_while_the_launch_finishes_are_told_after_it(self):
        config.rulebook_path(SEAT).write_text(config.seat_rulebook(SEAT))   # what it hands

        def harness_up(*_args, **_kw):
            # the rulebook changes as the harness comes up; a prompt then waits on the
            # launch's lock and carries nothing, so the next one after the launch tells it
            (config.HOME / "rules.md").write_text("A newer rule.\n")
            self.assertEqual(self.prompt(), "")

        with patch.object(orch, "start", side_effect=harness_up), patch.object(statusbar, "dress"):
            orch.launch(SEAT, "opus", str(self.root), ["true"], OWN)
        self.assertIn("has changed", self.prompt())

    def test_a_launch_that_fails_to_start_keeps_the_record_of_the_harness_still_there(self):
        self.handed(BEFORE)
        with patch.object(orch, "start", side_effect=config.Error("tmux refused")), \
                self.assertRaises(config.Error):
            config.rulebook_path(SEAT).write_text(config.seat_rulebook(SEAT))
            orch.launch(SEAT, "opus", str(self.root), ["true"], OWN)
        self.assertEqual(config.session_records()[SEAT]["rulebook_sha"],
                         config.rulebook_digest(BEFORE))

    def test_a_reopen_that_fails_leaves_an_old_seat_to_be_told(self):
        self.handed(BEFORE, recorded=False)      # its launch file is its only word on BEFORE
        from tools import rulebook

        def command(*_args, **_kw):
            rulebook.write(SEAT)                 # the adapter rewrites it building the command
            return ["true"]

        def tmux(*args, **_kw):
            if args[0] == "show-options":
                return 0, "%7"
            if args[0] == "display-message":
                return 0, SEAT
            if args[0] == "respawn-pane":
                return 1, "tmux refused; the old pane is still running"
            self.fail(f"unexpected tmux command: {args}")

        live = {"name": SEAT, "path": str(self.root), "exited": False, "legacy": False}
        with patch.object(orch, "find", return_value=live), \
                patch.object(config, "accounts", return_value=["default"]), \
                patch.object(orch, "opened", return_value=True), \
                patch.object(orch, "command", side_effect=command), \
                patch.object(orch, "seat_command", return_value="true"), \
                patch.object(orch, "tmux_out", side_effect=tmux), \
                self.assertRaises(config.Error):
            orch.resume(self.cfg, SEAT, log=lambda _: None, hand_over=False, account="default")
        self.assertEqual(config.session_records()[SEAT]["rulebook_sha"],
                         config.rulebook_digest(BEFORE))
        self.assertIn("has changed", self.prompt())

    def test_a_model_switch_that_fails_leaves_an_old_seat_to_be_told(self):
        self.handed(BEFORE, recorded=False)
        from tools import rulebook

        def command(*_args, **_kw):
            rulebook.write(SEAT)                 # the adapter rewrites it building the command
            return ["true"]

        def tmux(*args, **_kw):
            if args[0] == "show-options":
                return 0, "%7"
            if args[0] == "display-message":
                return 0, SEAT
            if args[0] == "respawn-pane":
                return 1, "tmux refused; the old pane is still running"
            self.fail(f"unexpected tmux command: {args}")

        live = {"name": SEAT, "path": str(self.root), "exited": False, "legacy": False}
        with patch.object(orch, "_switch_plan", return_value=("", None)), \
                patch.object(orch, "find", return_value=live), \
                patch.object(orch, "command", side_effect=command), \
                patch.object(orch, "seat_command", return_value="true"), \
                patch.object(orch, "tmux_out", side_effect=tmux):
            self.assertIn("tmux refused", orch.switch_orchestrator(self.cfg, SEAT, "fable",
                                                                    providers={}))
        self.assertEqual(config.session_records()[SEAT]["orchestrator"], "opus")
        self.assertIn("has changed", self.prompt())

    def test_a_launch_records_the_rulebook_it_handed(self):
        self.handed(BEFORE, recorded=False)
        with patch.object(orch, "start"), patch.object(statusbar, "dress"):
            orch.launch(SEAT, "opus", str(self.root), ["true"], None)
        self.assertEqual(config.session_records()[SEAT]["rulebook_sha"],
                         config.rulebook_digest(BEFORE))


    def test_a_rulebook_said_read_stays_read_after_a_rename(self):
        self.handed(BEFORE)
        self.said_read(self.prompt())
        config.rename_session(SEAT, "acme-renamed")
        self.assertEqual(self.prompt(), "")

    def test_a_client_nested_in_the_pane_leaves_the_seat_s_reading_alone(self):
        self.handed(BEFORE)
        notice = self.prompt()
        self.assertEqual(self.prompt(conversation="acme-nested"), "")
        self.said_read(notice)
        self.assertEqual(self.prompt(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
