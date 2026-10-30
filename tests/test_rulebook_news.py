"""A seat open across a rulebook change is told with its next prompt, through its prompt hook.

Offline: a temporary HOME, real seat records and the real hooks/seat-state.sh, outside tmux.
"""

from contextlib import contextmanager
import json
import os
import re
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify, orch, statusbar, watch
from agentkit.guard import commands
from agentkit.harness import codex

SEAT = "acme-fix"
# one rule from the seat's rules now (`setUp`): a change short enough to carry inline, which
# tests/test_key_rulebook_news_too_long.py says the shipped rules alone are not
BEFORE = f"{(REPO / 'orchestrator.md').read_text().rstrip()}\n\nAn older rule.\n"
OWN = "0f5d6e2a-6a43-4c3e-9b0e-3a1f6c2d9e10"      # the conversation the seat's launch handed out
OWNED = {"conversation": OWN, "id_source": "launcher", "resumable": True}
TOLD = '"additionalContext"'                        # what a notice rides in, inline or naming a file


class RulebookNews(Sandbox):
    def setUp(self):
        super().setUp()
        # the hook's own process and these readers share one HOME
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root), **OWNED})
        (config.HOME / "rules.md").write_text("The rule now.\n")

    def handed(self, text, name=SEAT, recorded=True):
        """The rulebook a launch under `name` handed the seat."""
        config.rulebook_path(name).write_text(text)
        if recorded:
            config.update_session(config.resolve_session(name),
                                  rulebook_sha=config.rulebook_digest(text))

    def prompt(self, event="UserPromptSubmit", session=SEAT, conversation=OWN, source=None, **env):
        result = subprocess.run(
            ["bash", str(REPO / "hooks/seat-state.sh")],
            input=json.dumps({"hook_event_name": event, "prompt": "carry on",
                              "session_id": conversation, **({"source": source} if source else {})}),
            text=True, capture_output=True, timeout=30,
            env={"HOME": str(self.root), "PATH": os.environ["PATH"],
                 "AGENTKIT_SESSION": session, "AK_RUN_ROLE": "orchestrator", **env})
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return result.stdout

    def test_a_conversation_clear_started_is_told_again(self):
        # /clear keeps the harness and its launch rulebook, and drops what the old one read
        self.handed(BEFORE)
        self.assertIn(TOLD, self.prompt())
        cleared = "c3a1f2e4-5b6d-4e7f-8a9b-0c1d2e3f4a5b"
        config.update_session(SEAT, conversation=cleared, id_source="claude-hook")
        self.assertIn(TOLD, self.prompt(conversation=cleared))
        self.assertEqual(self.prompt(conversation=cleared), "")

    def test_a_conversation_its_harness_does_not_vouch_for_is_never_told(self):
        # an id the record holds without the launcher's or the harness's own word for it
        self.handed(BEFORE)
        config.update_session(SEAT, id_source="discovered", resumable=False)
        self.assertEqual(self.prompt(), "")
        self.assertNotIn("rulebook_read", config.session_records()[SEAT])

    def test_a_client_started_inside_the_seat_is_never_told(self):
        # it inherits the seat's name; its conversation is its own, never the seat's
        self.handed(BEFORE)
        nested = "7c1e0a55-2b7d-4f0e-8a51-5d8b1f4c3a22"
        self.assertEqual(self.prompt(conversation=nested), "")
        self.assertEqual(self.prompt("Stop", conversation=nested), "")
        self.assertNotIn("rulebook_read", config.session_records()[SEAT])
        self.assertIn(TOLD, self.prompt())

    def test_a_current_rulebook_says_nothing(self):
        self.handed(config.seat_rulebook(SEAT))
        self.assertEqual(self.prompt(), "")

    def test_a_seat_launched_before_the_record_kept_it_is_told(self):
        # what it was handed is unknown: it is told, never guessed at from a file
        self.handed(config.seat_rulebook(SEAT), recorded=False)
        self.assertIn(TOLD, self.prompt())

    def test_a_record_write_that_fails_hands_nothing_and_the_next_prompt_does(self):
        self.handed(BEFORE, recorded=False)      # its file is its only word on its launch
        blocked = config.session_path(SEAT).with_suffix(".tmp")
        blocked.mkdir()                          # the record cannot be written for now
        self.assertEqual(self.prompt(), "")
        blocked.rmdir()
        self.assertIn(TOLD, self.prompt())

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

        def starting(*_args, **_kwargs):
            # the rules change and the old harness, still in its pane, prompts before it goes
            (config.HOME / "rules.md").write_text("A newer rule.\n")
            orch.rulebook_news(SEAT, OWN)

        with patch.object(orch, "_start_harness", side_effect=starting):
            orch.launch(SEAT, "opus", str(self.root), ["true"], OWN)
        self.assertEqual(config.session_records()[SEAT]["rulebook_sha"],
                         config.rulebook_digest(config.rulebook_path(SEAT).read_bytes()))
        self.assertNotIn("A newer rule.", config.rulebook_path(SEAT).read_text())

    def test_only_a_seats_prompt_hears_it(self):
        self.handed(BEFORE)
        for event, env in (("Stop", {}), ("Notification", {}),
                           ("UserPromptSubmit", {"AK_RUN_ROLE": "worker"}),
                           ("UserPromptSubmit", {"AGENTKIT_SESSION": ""})):
            with self.subTest(event=event, env=env):
                self.assertEqual(self.prompt(event, **env), "")
        self.assertNotIn("rulebook_read", config.session_records()[SEAT])

    def test_a_harness_whose_prompt_takes_no_context_reads_it_at_its_next_launch(self):
        config.save_session(self.cfg, SEAT, "mimo", ["mimo"], {"cwd": str(self.root), **OWNED})
        self.assertFalse(orch.seat_plugin(config.session_records()[SEAT]).prompt_context)
        self.handed(BEFORE)
        self.assertEqual(self.prompt(), "")
        self.assertNotIn("rulebook_read", config.session_records()[SEAT])

    def test_a_renamed_seat_is_told_what_changed_since_its_launch_under_its_old_name(self):
        config.save_session(self.cfg, "acme-old", "opus", ["astra"], {"cwd": str(self.root), **OWNED})
        rules = config.HOME / "rules.md"
        rules.write_text("Rule one.\n")
        self.handed(config.seat_rulebook("acme-old"), name="acme-old")
        rules.write_text("Rule two.\n")
        config.rename_session("acme-old", "acme-new")
        told = json.loads(self.prompt(session="acme-old"))["hookSpecificOutput"]
        # the launch copy stays under the name it was launched with
        self.assertIn("\n-Rule one.\n+Rule two.\n", told["additionalContext"])
        self.assertEqual(config.session_records()["acme-new"]["rulebook_read"],
                         {"conversation": OWN,
                          "sha": config.rulebook_digest(config.seat_rulebook("acme-new"))})

    def test_a_change_is_told_against_any_copy_left_of_the_rulebook_held(self):
        # a rename can land between a hand-over's record and its `held` file, and a seat that
        # said it read its rulebook before prompts carried it may keep it only in `rules`
        rules = config.HOME / "rules.md"
        for kind in ("held", "rules"):
            with self.subTest(kind=kind):
                old, new = f"acme-{kind}", f"acme-{kind}-renamed"
                config.save_session(self.cfg, old, "opus", ["astra"],
                                    {"cwd": str(self.root), **OWNED})
                rules.write_text("Rule one.\n")
                held = config.seat_rulebook(old)
                config.update_session(old, rulebook_read={
                    "conversation": OWN, "sha": config.rulebook_digest(held)})
                config.rename_session(old, new)
                config.seat_file(kind, old).write_text(held)     # left under the old name
                rules.write_text("Rule two.\n")
                told = json.loads(self.prompt(session=new))["hookSpecificOutput"]
                self.assertIn("\n-Rule one.\n+Rule two.\n", told["additionalContext"])

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
        self.assertIn(TOLD, self.prompt(conversation=thread))

    def test_a_prompt_typed_while_a_delivery_holds_the_seat_is_told(self):
        self.handed(BEFORE)
        with notify.session_lock(SEAT):        # a delivery typing this very prompt
            self.assertIn(TOLD, self.prompt())
        self.assertEqual(self.prompt(), "")

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
        self.assertIn(TOLD, heard[0])

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
                patch.object(watch, "pane_text", return_value=f"❯ {line}"), \
                patch.object(watch, "asking", return_value=False):
            watch.type_at_prompt({"name": SEAT}, line, lambda _line: None, cfg=self.cfg,
                                 typed={"line": line, "seat": None})
        self.assertIn(TOLD, heard[0])

    def test_a_seat_from_before_whose_launch_file_was_rewritten_is_still_told(self):
        # a reopen that failed rewrote its launch file to the current rules first: the
        # harness that survived still holds what it was opened with
        for seat, now in (("acme-same", "acme-same"), ("acme-was", "acme-now")):
            with self.subTest(renamed=seat != now):
                config.save_session(self.cfg, seat, "opus", ["astra"],
                                    {"cwd": str(self.root), **OWNED})
                self.handed(BEFORE, name=seat, recorded=False)
                if now != seat:
                    config.rename_session(seat, now)
                config.rulebook_path(now).write_text(config.seat_rulebook(now))
                self.assertIn(TOLD, self.prompt(session=seat))

    def test_its_record_writes_never_land_over_a_rename(self):
        # while a rename holds the seat's lock: a launch waits, and a prompt's write, taking
        # only the record's own lock, lands before it and moves with the record
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
        # `orch.stamp` writes `seen` from a read made before the prompt's hand-over
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
            if args[0] == "set-environment":
                self.assertTrue(all(command[:3] == ["set-environment", "-t", f"={SEAT}:"]
                                    for command in commands(args)))
                return 0, ""
            if args[0] == "respawn-pane":
                return 1, "tmux refused; the old pane is still running"
            self.fail(f"unexpected tmux command: {args}")

        live = {"name": SEAT, "path": str(self.root), "exited": False, "legacy": False}
        with patch.object(orch, "find", return_value=live), \
                patch.object(config, "accounts", return_value=["default"]), \
                patch.object(orch, "opened", return_value=True), \
                patch.object(orch, "command", side_effect=command), \
                patch.object(orch, "seat_command", return_value=("true", self.root / "launch")), \
                patch.object(orch, "tmux_out", side_effect=tmux), \
                self.assertRaises(config.Error):
            orch.resume(self.cfg, SEAT, log=lambda _: None, hand_over=False, account="default")
        self.assertIn(TOLD, self.prompt())

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
            if args[0] == "set-environment":
                self.assertTrue(all(command[:3] == ["set-environment", "-t", f"={SEAT}:"]
                                    for command in commands(args)))
                return 0, ""
            if args[0] == "respawn-pane":
                return 1, "tmux refused; the old pane is still running"
            if args[0] == "capture-pane":            # the move's look at the seat's screen
                return 0, (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
            self.fail(f"unexpected tmux command: {args}")

        live = {"name": SEAT, "path": str(self.root), "exited": False, "legacy": False}
        with patch.object(orch, "_switch_plan", return_value=("", None)), \
                patch.object(orch, "find", return_value=live), \
                patch.object(orch, "command", side_effect=command), \
                patch.object(orch, "seat_command", return_value=("true", self.root / "launch")), \
                patch.object(orch, "tmux_out", side_effect=tmux):
            self.assertIn("tmux refused", orch.switch_orchestrator(self.cfg, SEAT, "fable",
                                                                    providers={}))
        self.assertEqual(config.session_records()[SEAT]["orchestrator"], "opus")
        self.assertIn(TOLD, self.prompt())

    def test_a_launch_records_the_rulebook_it_handed(self):
        self.handed(BEFORE, recorded=False)
        with patch.object(orch, "start"), patch.object(statusbar, "dress"):
            orch.launch(SEAT, "opus", str(self.root), ["true"], None)
        self.assertEqual(config.session_records()[SEAT]["rulebook_sha"],
                         config.rulebook_digest(BEFORE))


    def test_a_rulebook_handed_stays_held_after_a_rename(self):
        self.handed(BEFORE)
        self.assertIn(TOLD, self.prompt())
        config.rename_session(SEAT, "acme-renamed")
        self.assertEqual(self.prompt(), "")

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=Acme", "-c",
                               "user.email=acme@example.com", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def test_a_seat_reads_its_project_s_merged_agents_md_and_is_told_when_a_merge_changes_it(self):
        git = self.git
        upstream, checkout = self.root / "acme-origin", self.root / "acme"
        git(self.root, "init", "-q", "-b", "main", str(upstream))
        (upstream / "AGENTS.md").write_text("---\ntests: python3 acme_gate.py\n---\n# Acme\n\nAcme rule one.\n")
        git(upstream, "add", "AGENTS.md")
        git(upstream, "commit", "-qm", "rules")
        git(self.root, "clone", "-q", str(upstream), str(checkout))
        config.update_session(SEAT, repo=str(checkout))
        self.handed(config.seat_rulebook(SEAT))
        self.assertIn("Acme rule one.", config.seat_rulebook(SEAT))
        self.assertNotIn("acme_gate", config.seat_rulebook(SEAT))
        (checkout / "AGENTS.md").write_text("Acme draft nobody merged.\n")
        self.assertEqual(self.prompt(), "")
        # merged upstream, and nothing else fetches it: the tick's pass does; a section the
        # rulebook also holds, in a fenced template here, is carried as committed
        held = next(part for part in re.split(r"(?m)^(?=## )", config.rulebook_text())
                    if part.startswith("## "))
        rules = f"# Acme\n\nAcme rule two. Every README holds:\n\n```markdown\n{held.strip()}\n```\n"
        (upstream / "AGENTS.md").write_text(rules)
        git(upstream, "commit", "-qam", "rule two")
        self.assertEqual(self.prompt(), "")
        orch.fetch_projects()
        told = json.loads(self.prompt())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("\n+Acme rule two. Every README holds:\n", told)
        self.assertIn(rules.strip(), config.seat_rulebook(SEAT))
        self.assertNotIn("Acme draft", told)

    def test_the_tick_reads_origin_s_current_default_branch_whatever_the_checkout_holds(self):
        git = self.git
        for layout in ("pushed, never cloned", "no tracking ref", "one branch followed",
                       "default moved", "a branch named origin/HEAD"):
            with self.subTest(layout):
                root = self.root / layout.replace(" ", "-").replace("/", "-")
                upstream, checkout = root / "acme-origin.git", root / "acme"
                other = root / "acme-elsewhere"
                git(self.root, "init", "-q", "--bare", "-b", "main", str(upstream))
                git(self.root, "clone", "-q", str(upstream), str(other))
                (other / "AGENTS.md").write_text("# Acme\n\nAcme policy one.\n")
                git(other, "add", "AGENTS.md")
                git(other, "commit", "-qm", "rules")
                git(other, "push", "-q", "origin", "HEAD:main")
                if layout == "pushed, never cloned":
                    git(self.root, "init", "-q", "-b", "main", str(checkout))
                    git(checkout, "remote", "add", "origin", str(upstream))
                    git(checkout, "fetch", "-q", "origin", "main:refs/remotes/origin/main")
                else:
                    git(self.root, "clone", "-q", str(upstream), str(checkout))
                if layout == "no tracking ref":
                    git(checkout, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
                    git(checkout, "update-ref", "-d", "refs/remotes/origin/main")
                if layout == "one branch followed":
                    git(checkout, "config", "remote.origin.fetch",
                        "+refs/heads/dev:refs/remotes/origin/dev")
                if layout == "a branch named origin/HEAD":
                    git(checkout, "checkout", "-qb", "draft")
                    (checkout / "AGENTS.md").write_text("# Acme\n\nAcme draft policy.\n")
                    git(checkout, "commit", "-qam", "draft rules")
                    git(checkout, "branch", "origin/HEAD")   # what the short name finds first
                # merged since, from elsewhere -- on a new default branch where origin moved it
                (other / "AGENTS.md").write_text("# Acme\n\nAcme policy two.\n")
                git(other, "commit", "-qam", "rule two")
                if layout == "default moved":
                    git(other, "push", "-q", "origin", "HEAD:release")
                    git(upstream, "symbolic-ref", "HEAD", "refs/heads/release")
                else:
                    git(other, "push", "-q", "origin", "HEAD:main")
                config.update_session(SEAT, repo=str(checkout))
                orch.fetch_projects()
                book = config.seat_rulebook(SEAT)
                self.assertIn("Acme policy two.", book)
                self.assertNotIn("Acme policy one.", book)
                self.assertNotIn("Acme draft policy.", book)

    def test_a_project_the_tick_cannot_fetch_is_named_after_every_other_is_fetched(self):
        git = self.git
        upstream, checkout = self.root / "acme-origin", self.root / "z-acme"
        git(self.root, "init", "-q", "-b", "main", str(upstream))
        (upstream / "AGENTS.md").write_text("# Acme\n\nAcme policy one.\n")
        git(upstream, "add", "AGENTS.md")
        git(upstream, "commit", "-qm", "rules")
        git(self.root, "clone", "-q", str(upstream), str(checkout))
        (upstream / "AGENTS.md").write_text("# Acme\n\nAcme policy two.\n")
        git(upstream, "commit", "-qam", "rule two")
        broken = self.root / "a-acme-archived"          # sorted first, and no repository
        broken.mkdir()
        gone = self.root / "b-acme-gone"                # its directory deleted since
        config.update_session(SEAT, repo=str(checkout))
        for name, path in (("acme-archived", broken), ("acme-gone", gone)):
            config.save_session(self.cfg, name, "opus", ["astra"],
                                {"cwd": str(path), "repo": str(path), **OWNED})
        with self.assertRaisesRegex(config.Error, "a-acme-archived.*; .*b-acme-gone"):
            orch.fetch_projects()
        self.assertIn("Acme policy two.", config.seat_rulebook(SEAT))

    def test_a_project_whose_name_ends_in_whitespace_is_read_and_fetched(self):
        git = self.git
        upstream = self.root / "acme-origin"
        git(self.root, "init", "-q", "-b", "main", str(upstream))
        (upstream / "AGENTS.md").write_text("# Acme\n\nAcme policy one.\n")
        git(upstream, "add", "AGENTS.md")
        git(upstream, "commit", "-qm", "rules")
        for name in ("acme ", "acme\t", "acme\n"):
            with self.subTest(repr(name)):
                checkout = self.root / name
                git(self.root, "clone", "-q", str(upstream), str(checkout))
                (upstream / "AGENTS.md").write_text(f"# Acme\n\nAcme policy for {name!r}.\n")
                git(upstream, "commit", "-qam", "rule two")
                config.update_session(SEAT, repo=str(checkout))
                orch.fetch_projects()
                self.assertIn(f"Acme policy for {name!r}.", config.seat_rulebook(SEAT))

    def test_a_project_whose_repository_is_gone_gets_neither_a_parent_s_rules_nor_fetch(self):
        git = self.git
        for layout in (".git moved away", ".git emptied", "parent named with a colon"):
            with self.subTest(layout):
                root = self.root / layout.replace(" ", "-")
                hub = root / ("acme:hub" if "colon" in layout else "acme-hub")
                upstream, elsewhere = root / "acme-hub-origin.git", root / "acme-hub-elsewhere"
                child = hub / "acme-archived"
                git(self.root, "init", "-q", "--bare", "-b", "main", str(upstream))
                git(self.root, "clone", "-q", str(upstream), str(hub))
                (hub / "AGENTS.md").write_text("Acme hub rule.\n")
                child.mkdir()
                (child / "AGENTS.md").write_text("Acme archived rule.\n")
                git(hub, "add", ".")
                git(hub, "commit", "-qm", "hub rules")
                git(hub, "push", "-q", "origin", "main")
                git(hub, "remote", "set-head", "origin", "--auto")   # what a seat reads
                git(self.root, "clone", "-q", str(upstream), str(elsewhere))
                git(elsewhere, "commit", "-q", "--allow-empty", "-m", "merged since")
                git(elsewhere, "push", "-q", "origin", "main")
                git(child, "init", "-q", "-b", "main")
                git(child, "add", "AGENTS.md")
                git(child, "commit", "-qm", "own rules")
                (child / ".git").rename(root / "acme-archived.git")
                if layout == ".git emptied":
                    (child / ".git").mkdir()
                fetched = git(hub, "rev-parse", "refs/remotes/origin/main")
                config.update_session(SEAT, repo=str(child))
                with self.assertRaisesRegex(config.Error, "acme-archived"):
                    orch.fetch_projects()
                self.assertEqual(git(hub, "rev-parse", "refs/remotes/origin/main"), fetched)
                book = config.seat_rulebook(SEAT)
                self.assertNotIn("Acme hub rule.", book)
                self.assertNotIn("Acme archived rule.", book)

    def test_a_repository_named_by_inherited_git_variables_is_never_read_or_fetched(self):
        git = self.git
        clones = {}
        for name in ("acme", "acme-other"):
            upstream, checkout = self.root / f"{name}-origin", self.root / name
            git(self.root, "init", "-q", "-b", "main", str(upstream))
            (upstream / "AGENTS.md").write_text(f"# {name}\n\n{name} policy one.\n")
            git(upstream, "add", "AGENTS.md")
            git(upstream, "commit", "-qm", "rules")
            git(self.root, "clone", "-q", str(upstream), str(checkout))
            (upstream / "AGENTS.md").write_text(f"# {name}\n\n{name} policy two.\n")
            git(upstream, "commit", "-qam", "rule two")
            clones[name] = checkout
        other = clones["acme-other"]
        before = git(other, "rev-parse", "refs/remotes/origin/main")
        config.update_session(SEAT, repo=str(clones["acme"]))
        with patch.dict(os.environ, {"GIT_DIR": str(other / ".git"),
                                     "GIT_COMMON_DIR": str(other / ".git"),
                                     "GIT_WORK_TREE": str(other)}):
            orch.fetch_projects()
            book = config.seat_rulebook(SEAT)
        self.assertIn("acme policy two.", book)
        self.assertNotIn("acme-other", book)
        self.assertEqual(git(other, "rev-parse", "refs/remotes/origin/main"), before)

    def test_a_merge_fetched_while_the_rules_are_read_never_hands_a_link_s_text(self):
        git = self.git
        checkout = self.root / "acme"
        git(self.root, "init", "-q", "-b", "main", str(checkout))
        (checkout / "AGENTS.md").write_text("Acme merged rule.\n")
        git(checkout, "add", "AGENTS.md")
        git(checkout, "commit", "-qm", "rules")
        regular = git(checkout, "rev-parse", "HEAD")
        (checkout / "AGENTS.md").unlink()
        (checkout / "AGENTS.md").symlink_to("acme-link-target")
        git(checkout, "add", "AGENTS.md")
        git(checkout, "commit", "-qm", "rules become a link")
        linked = git(checkout, "rev-parse", "HEAD")
        git(checkout, "update-ref", "refs/remotes/origin/main", regular)
        git(checkout, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        config.update_session(SEAT, repo=str(checkout))
        real = subprocess.run

        def fetched_meanwhile(argv, **kwargs):
            done = real(argv, **kwargs)
            if "ls-tree" in argv:
                git(checkout, "update-ref", "refs/remotes/origin/main", linked)
            return done

        with patch.object(subprocess, "run", side_effect=fetched_meanwhile):
            book = config.seat_rulebook(SEAT)
        self.assertIn("Acme merged rule.", book)
        self.assertNotIn("acme-link-target", book)


if __name__ == "__main__":
    unittest.main(verbosity=2)
