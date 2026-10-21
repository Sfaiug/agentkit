"""An unnamed seat's stops are sent back to name it, on every harness, a question aside.

Claude Code, Codex and Grok Build stop through hooks/orchestrator-stop.sh, which answers with the
naming line; Muse, OpenCode and Antigravity have no such hook, and the tick types that line.
A question to the owner still ends the turn, and the hook's two blocks a turn hold as for any
stop.  The seat owes nothing, so once named the same stop stands.  Offline: a fake tmux, fake
adapters and a throwaway HOME; the hook runs as its harness runs it, JSON on stdin.
"""

import json
import os
import subprocess
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from fixtures.seats import cursor_row
from agentkit import config, menu, notify, orch, watch

SEAT, SAID = "acme-api", "The parser is in place."
# each hookless harness's empty composer row on its prompt screen, and that row holding a line
TYPED = {"muse": ("\n❯\n", "\n❯ {}\n"), "antigravity": ("\n>\n", "\n> {}\n"),
         "opencode": ('┃  Ask anything… "What is the tech stack of this project?"',
                      "┃  {}")}


class UnnamedSeatNamesItself(Sandbox):
    def setUp(self):
        super().setUp()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "AK_RUN_ROLE": "orchestrator", notify.SINK_ENV: "dry-run",
            "AGENTKIT_DISCORD_WEBHOOK": "", config.SESSION_ENV: SEAT,
            config.ADAPTER_DIR_ENV: str(adapters)}))
        config.save_session(self.cfg, SEAT, "fable", ["opus"], {"cwd": str(self.root)})
        self.seat = {"name": SEAT, "created": 1, "attached": False, "exited": False,
                     "legacy": False, "resumable": False}
        listed = lambda *_a, **_k: [dict(self.seat)]
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "listing", side_effect=listed))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              side_effect=lambda *_a, **_k: (self.harness, "m")))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch.time, "sleep", lambda _s: None))
        self.harness, self.sent = "muse", []

    def tmux(self, *args, **_kw):
        if args[0] == "send-keys" and "-l" in args:
            self.sent.append(args[-1])
            empty, row = TYPED[self.harness]
            self.pane = self.pane.replace(empty, row.format(args[-1]))
        elif args[0] == "send-keys":
            self.pane = (REPO / f"tests/fixtures/{self.harness}-working-pane.txt").read_text()
        if args[-1] == "#{cursor_y}":
            return 0, cursor_row(self.pane)
        return 0, self.pane if args[0] == "capture-pane" else ""

    def hook(self, blocks=0, **payload):
        """The reason hooks/orchestrator-stop.sh sends the stop back with, or "" where it stands."""
        home = self.root / "hook-home" / ".agentkit"
        home.mkdir(parents=True, exist_ok=True)
        for name, target in (("state", config.STATE), ("runs", config.RUNS)):
            if not (home / name).is_symlink():
                (home / name).symlink_to(target)
        (config.STATE / f"stop-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "turn": time.time() - 60, "blocks": blocks}))
        done = subprocess.run(["bash", str(REPO / "hooks/orchestrator-stop.sh")], text=True,
                              capture_output=True, input=json.dumps({"hook_event_name": "Stop",
                                                                     **payload}),
                              env={"PATH": os.environ["PATH"], "HOME": str(home.parent),
                                   "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["reason"] if done.stdout.strip() else ""

    def tick(self):
        """What the tick types at the seat, stopped at its prompt long past STALL_WAIT."""
        now, before = time.time(), len(self.sent)
        self.pane = (REPO / f"tests/fixtures/{self.harness}-prompt-pane.txt").read_text()
        watch.seat_write(SEAT, state="at_prompt", turn_began=now - 7200, stop_said_at=now - 3600,
                         stop_nudged=None)
        watch.stop_nudge(self.seat, self.harness, self.pane, notify.last(SEAT),
                         menu.run_records(), False, lambda line: None)
        return self.sent[before:]

    def judged(self, message=SAID):
        """Every harness's answer to the same stop: the hook's reason, then each tick's lines."""
        transcript = self.root / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": message}]}}) + "\n")
        said = [self.hook(transcript_path=str(transcript)),
                self.hook(last_assistant_message=message)]
        for harness in TYPED:
            self.harness = harness
            said.append(self.tick())
        return said

    def test_an_unnamed_seat_is_sent_back_to_name_itself_until_it_has(self):
        config.update_session(SEAT, unnamed=True)
        self.assertEqual(self.judged(), [config.NAME_LINE] * 2 + [[config.NAME_LINE]] * 3)
        self.assertIn(config.NAME_LINE, config.seat_rulebook(SEAT))
        config.update_session(SEAT, unnamed=None)      # what `ak orch rename --auto` leaves
        self.assertEqual(self.judged(), [""] * 2 + [[]] * 3)
        self.assertNotIn(config.NAME_LINE, config.seat_rulebook(SEAT))

    def test_a_question_to_the_owner_still_ends_the_turn(self):
        config.update_session(SEAT, unnamed=True)
        notify.record(SEAT, "needs", "Which environment should this use?")
        self.assertEqual(self.judged("Which environment should this use?"), [""] * 2 + [[]] * 3)

    def test_the_third_stop_of_a_turn_stands_as_any_other_does(self):
        config.update_session(SEAT, unnamed=True)
        self.assertEqual(self.hook(blocks=1, last_assistant_message=SAID), config.NAME_LINE)
        self.assertEqual(self.hook(blocks=2, last_assistant_message=SAID), "")


if __name__ == "__main__":
    unittest.main()
