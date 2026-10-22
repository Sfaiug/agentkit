"""The answer key fires ak's hooks as a harness does, and reads back what they did.

A hook test holds only if tests/fixtures/hookdrive.py takes the hooks ak's adapter registered and
runs each command the way its harness would: the matching ones, in order, with the event's JSON
on stdin and the seat's environment, the pane's too inside one, keeping what each printed.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks, adapter, transcript

# A hook's stand-in: it keeps the event it was handed and the environment it ran in.
PROBE = """import json, os, sys
env = {key: os.environ.get(key) for key in ("AGENTKIT_SESSION", "AK_RUN_ROLE", "TMUX",
                                            "TMUX_PANE")}
with open(sys.argv[1], "a") as log:
    log.write(json.dumps({"tag": sys.argv[2], "event": json.load(sys.stdin), "env": env}) + "\\n")
"""


class Registered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def test_each_adapter_registers_its_commands_and_a_matcher_picks_them_by_tool(self):
        claude = Hooks(self.home)
        self.assertEqual(claude.file, self.home.path / ".claude/settings.json")
        self.assertEqual(len(claude.commands("Stop")), 2)
        self.assertEqual(claude.commands("PreToolUse", tool="Bash"), [])
        self.assertEqual(len(claude.commands("PreToolUse", tool="AskUserQuestion")), 1)
        self.assertTrue(Hooks(self.home, "grokbuild").commands("Stop"))

    def test_an_install_that_fails_fails_the_test_asking_for_it(self):
        with Home() as home:
            home.write(".claude/settings.json", "{not json")
            with self.assertRaises(AssertionError):
                Hooks(home)

    def test_an_adapters_verb_takes_the_event_on_stdin_in_the_seats_environment(self):
        fired = adapter(self.home, "muse", "hook", payload={"hook_event_name": "Stop"},
                        seat="fix-api")
        self.assertEqual(fired.code, 0, fired.err)
        fact = json.loads((self.home.path / ".agentkit/state/hook-fix-api.json").read_text())
        self.assertEqual((fact["session"], fact["event"]), ("fix-api", "Stop"))

    def test_a_transcript_is_a_line_per_entry_a_string_being_said_by_the_model(self):
        path = transcript(self.home, "acme", "Done.", {"type": "user", "message": {}})
        lines = [json.loads(line) for line in Path(path).read_text().splitlines()]
        self.assertEqual(lines, [{"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "Done."}]}},
            {"type": "user", "message": {}}])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Firing(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.hooks = Hooks(self.home)
        self.log = self.home.root / "probe.jsonl"
        script = self.home.write("probe.py", PROBE)
        probe = {tag: shlex.join(["python3", str(script), str(self.log), tag])
                 for tag in ("first", "second", "bash", "asks", "prompt")}
        self.hooks.file.write_text(json.dumps({"hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": probe["prompt"]}]}],
            "Stop": [{"hooks": [{"type": "command", "command": probe["first"]}]},
                     {"hooks": [{"type": "command", "command":
                                 probe["second"] + "; echo '{\"decision\": \"block\"}'; "
                                 "echo late >&2; exit 3"}]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
                                                          "command": probe["bash"]}]},
                           {"matcher": "AskUserQuestion|ExitPlanMode", "hooks": [
                               {"type": "command", "command": probe["asks"]}]}]}}))

    def heard(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_every_command_runs_in_order_with_the_event_and_the_seats_name(self):
        fired = self.hooks.fire("Stop", {"session_id": "x"}, seat="acme",
                                env={"AK_RUN_ROLE": "worker"})
        self.assertEqual(fired, (3, '{"decision": "block"}\n', "late\n",
                                 [{"decision": "block"}]))
        env = {"AGENTKIT_SESSION": "acme", "AK_RUN_ROLE": "worker", "TMUX": None,
               "TMUX_PANE": None}
        event = {"hook_event_name": "Stop", "session_id": "x"}
        self.assertEqual(self.heard(), [{"tag": "first", "event": event, "env": env},
                                        {"tag": "second", "event": event, "env": env}])

    def test_a_tool_event_runs_only_the_commands_its_matcher_takes(self):
        self.hooks.fire("PreToolUse", {"tool_name": "ExitPlanMode"}, seat=None)
        self.assertEqual([(each["tag"], each["env"]["AGENTKIT_SESSION"])
                          for each in self.heard()], [("asks", None)])

    def test_inside_a_pane_the_hook_is_told_that_pane_on_its_server(self):
        seat = Seat(self.home, "acme")
        self.hooks.fire("Stop", seat="acme", pane=seat)
        env = self.heard()[0]["env"]
        self.assertEqual(env["TMUX_PANE"], seat.pane)
        socket = self.home.tmux("display-message", "-p", "-t", seat.pane, "#{socket_path}")
        self.assertEqual(env["TMUX"].split(",")[0], socket.out.strip())

    def test_the_owners_prompt_goes_into_the_seats_conversation_and_fires_in_its_pane(self):
        seat = Seat(self.home, "acme")
        self.hooks.prompt("8080", seat)
        [heard] = self.heard()
        self.assertEqual((heard["tag"], heard["event"]["prompt"], heard["env"]["TMUX_PANE"]),
                         ("prompt", "8080", seat.pane))
        [kept] = (self.home.path / ".claude/projects").glob("*/conv-acme.jsonl")
        self.assertTrue(kept.parent.name.endswith("-code-acme"), kept)
        [line] = map(json.loads, kept.read_text().splitlines())
        self.assertEqual((line["type"], line["message"]), ("user", {"role": "user",
                                                                     "content": "8080"}))
        self.assertRegex(line["timestamp"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


if __name__ == "__main__":
    unittest.main()
