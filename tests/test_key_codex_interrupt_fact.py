"""A Codex seat's Interrupt is written down every time, though it means what a Stop means.

The owner's Esc ends a Codex turn with an `Interrupt` event, which says the seat is at its
prompt, as a Stop does.  A notice that says only what the seat's fact (`hook-<seat>.json`)
already says is not written again, but an interrupt always is, with the moment it arrived: it is
the owner stopping the turn, so the seat rests whatever its plan still owes, and only the fact
can say a turn ended that way and when.  Black-box: a person opens a Codex seat with `ak orch`
from a terminal, on a `codex` of this test's own that reports hook support and keeps each command
line it is given; each command that launch registers for an event (`-c hooks.<event>=[...]`) is
then run as Codex runs it, with `sh -c`, the event's JSON on stdin in the seat's environment.
This test fails against `/bin/false`.
"""

import json
import sys
import time
import tomllib
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, Home
from fixtures.akterm import Terminal

# Codex as far as a seat's launch asks it: hook support on `--help`, then a server that ends.
CODEX = LOG + """case "$1" in --help) echo '  --dangerously-bypass-hook-trust' ;; esac
"""


class CodexInterrupt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.fake("codex", CODEX.format(python=sys.executable,
                                            log=str(cls.home.log("codex"))))
        term = Terminal(cls.home, "orch", "launch", "--model", "astra", "--workers", "astra")
        deadline = time.monotonic() + 60
        while not (cls.served() or term.status.exists() or time.monotonic() > deadline):
            time.sleep(0.05)
        flags = [argv[i + 1] for argv in cls.served() for i, word in enumerate(argv[:-1])
                 if word == "-c" and argv[i + 1].startswith("hooks.")]
        cls.hooks = {}
        for flag in flags:
            cls.hooks.update(tomllib.loads(flag)["hooks"])
        assert cls.hooks.get("Interrupt"), f"no hooks registered; the terminal shows:\n" \
                                           f"{term.screen()}"

    @classmethod
    def served(cls):
        return [argv for argv in cls.home.calls("codex") if argv[:1] == ["app-server"]]

    def seat(self, name):
        self.home.write(f".agentkit/state/session-{name}.json",
                        {"orchestrator": "astra", "workers": ["astra"]})
        return name

    def fire(self, event, seat, **payload):
        """That event through each command the launch registered for it; the seat's fact
        after it."""
        for group in self.hooks[event]:
            for hook in group["hooks"]:
                done = self.home.run("sh", "-c", hook["command"],
                                     input=json.dumps({"hook_event_name": event, **payload}),
                                     env={"AGENTKIT_SESSION": seat})
                self.assertEqual(done.code, 0, done.err)
        path = self.home.path / ".agentkit" / "state" / f"hook-{seat}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def test_an_interrupt_is_written_after_a_stop_and_again_after_itself(self):
        name = self.seat("acme")
        stopped = self.fire("Stop", name)
        self.assertEqual(stopped["event"], "Stop")
        first = self.fire("Interrupt", name, turn_id="turn-1")
        self.assertEqual((first["session"], first["event"]), (name, "Interrupt"))
        self.assertGreater(first["at"], stopped["at"])
        second = self.fire("Interrupt", name, turn_id="turn-2")
        self.assertEqual(second["event"], "Interrupt")
        self.assertGreater(second["at"], first["at"])

    def test_a_notice_saying_what_the_fact_says_is_not_written_again(self):
        # beside the interrupt: a second permission request asks what the first one asked
        name = self.seat("beta")
        self.fire("UserPromptSubmit", name, prompt="Touch a file outside the workspace.")
        asked = self.fire("PermissionRequest", name, tool_name="Bash", tool_use_id="exec-1")
        self.assertEqual((asked["event"], asked["kind"]), ("PermissionRequest", "Bash"))
        again = self.fire("PermissionRequest", name, tool_name="Bash", tool_use_id="exec-1")
        self.assertEqual(again, asked)


if __name__ == "__main__":
    unittest.main()
