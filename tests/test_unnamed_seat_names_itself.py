"""No turn of an unnamed seat ends before it names itself, on every harness.

Claude Code, Codex and Grok Build send a stop through hooks/orchestrator-stop.sh, which sends it
back with the naming line; Muse, OpenCode and Antigravity have no such hook, and the tick types
the same line at the stop instead.  The seat owes nothing, so once it has a name the same stop
stands.  Offline: a fake tmux, fake adapters, a throwaway HOME; the hook runs as its harness
runs it, JSON on stdin.
"""

import json
import os
import time
import unittest
from unittest.mock import patch

from fixtures import hooks

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, menu, notify, orch, watch

SEAT = "acme-api"
NUDGED = ("muse", "opencode", "antigravity")
# each harness's empty composer row on its prompt screen, and that row holding a typed line
TYPED = {"muse": ("\n❯\n", "\n❯ {}\n"), "antigravity": ("\n>\n", "\n> {}\n"),
         "opencode": ('┃  Ask anything… "What is the tech stack of this project?"',
                      "┃  {}")}
SAID = "The parser is in place."


class UnnamedSeatNamesItself(Sandbox):
    def setUp(self):
        super().setUp()
        adapters = self.root / "adapters"
        adapters.mkdir()
        for harness in NUDGED:
            script = adapters / f"{harness}.sh"
            script.write_text("#!/bin/sh\nexit 1\n")
            script.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_ROLE": "orchestrator",
            notify.SINK_ENV: "dry-run", "AGENTKIT_DISCORD_WEBHOOK": "",
            config.SESSION_ENV: SEAT, config.ADAPTER_DIR_ENV: str(adapters)}))
        config.save_session(self.cfg, SEAT, "fable", ["opus"],
                            {"cwd": str(self.root), "unnamed": True})
        self.seat = {"name": SEAT, "created": 1, "attached": False, "exited": False,
                     "legacy": False, "resumable": False}
        listed = lambda *_a, **_k: [dict(self.seat)]
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "listing", side_effect=listed))
        self.stack.enter_context(patch.object(
            watch, "seat_model", side_effect=lambda *_a, **_k: (self.harness, "meta")))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch.time, "sleep", lambda _s: None))
        self.harness, self.pane, self.sent = NUDGED[0], "", []

    def tmux(self, *args, socket=None, client=False, **_kw):
        """tmux for one seat: a line typed sits in the composer until its Enter takes it."""
        if args[0] == "capture-pane":
            return 0, self.pane
        if args[0] == "send-keys" and "-l" in args:
            self.sent.append(args[-1])
            empty, row = TYPED[self.harness]
            self.pane = self.screen("prompt").replace(empty, row.format(args[-1]))
        elif args[0] == "send-keys" and args[-1] == "Enter":
            self.pane = self.screen("working")
        return 0, ""

    def screen(self, kind):
        return (REPO / f"tests/fixtures/{self.harness}-{kind}-pane.txt").read_text()

    def named(self):
        """What `ak orch rename --auto` leaves in the seat's record."""
        config.update_session(SEAT, unnamed=None)

    def hook(self, **payload):
        """The reason hooks/orchestrator-stop.sh sends this turn's first stop back with, or ""."""
        home = self.root / "hook-home"
        for name, target in (("state", config.STATE), ("runs", config.RUNS)):
            link = home / ".agentkit" / name
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.is_symlink():
                link.symlink_to(target)
        (config.STATE / f"stop-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "turn": time.time() - 60, "blocks": 0}) + "\n")
        done = hooks.run(
            ["bash", str(REPO / "hooks/orchestrator-stop.sh")], text=True, capture_output=True,
            input=json.dumps({"hook_event_name": "Stop", "session_id": "fake", **payload}),
            env={"PATH": os.environ["PATH"], "HOME": str(home), "AGENTKIT_SESSION": SEAT,
                 "AK_RUN_ROLE": "orchestrator"})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["reason"] if done.stdout.strip() else ""

    def tick(self):
        """The lines the tick types at the seat, stopped at its prompt long past STALL_WAIT."""
        now, before = time.time(), len(self.sent)
        self.pane = self.screen("prompt")
        watch.seat_write(SEAT, state="at_prompt", turn_began=now - 7200,
                         stop_said_at=now - 3600, stop_nudged=None)
        watch.stop_nudge(self.seat, self.harness, self.pane, notify.last(SEAT),
                         menu.run_records(), False, lambda line: None)
        return self.sent[before:]

    def test_a_hook_sends_every_stop_of_an_unnamed_seat_back_to_name_it(self):
        transcript = self.root / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": SAID}]}}) + "\n")
        for harness, payload in (("claude", {"transcript_path": str(transcript)}),
                                 ("codex", {"last_assistant_message": SAID})):
            for label, recorded in (("nothing owed", lambda: None),
                                    ("a done", lambda: notify.record(SEAT, "done", SAID))):
                with self.subTest(harness=harness, case=label):
                    config.update_session(SEAT, unnamed=True)
                    recorded()
                    self.assertEqual(self.hook(**payload), config.NAME_LINE)
                    self.named()
                    self.assertEqual(self.hook(**payload), "")

    def test_the_tick_types_the_naming_line_where_no_hook_can(self):
        for harness in NUDGED:
            with self.subTest(harness=harness):
                self.harness = harness
                config.update_session(SEAT, unnamed=True)
                self.assertEqual(self.tick(), [config.NAME_LINE])
                self.named()
                self.assertEqual(self.tick(), [])

    def test_the_rulebook_says_the_line_the_stop_holds_it_to(self):
        self.assertIn(config.NAME_LINE, config.seat_rulebook(SEAT))
        self.named()
        self.assertNotIn(config.NAME_LINE, config.seat_rulebook(SEAT))


if __name__ == "__main__":
    unittest.main()
