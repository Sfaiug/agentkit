"""A Stop on a nudged harness records the background work it hands over.

A harness whose manifest says `[stop] enforce = "nudge"` runs no hooks/orchestrator-stop.sh, so
hooks/seat-state.sh writes its Stop, with the `holds` and `kind` that hook would have written
(`lifecycle.stop_fact`).  Where that hook runs, it stays the Stop's one writer.  Both hooks run
as a harness runs them, in a temporary HOME.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentkit import config  # noqa: E402

SUBAGENT = {"id": "bg1", "type": "subagent", "status": "running", "description": "read acme"}
SHELL = {"id": "bg2", "type": "shell", "status": "running", "description": "sleep 600"}


class NudgedStopHoldsBackgroundWork(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-nudged-stop-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".agentkit/state").mkdir(parents=True)
        (self.home / ".agentkit/config.toml").write_text(
            (REPO / "config.default.toml").read_text())
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.home / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ("TMUX", "TMUX_PANE", "AK_RUN_ROLE", config.ADAPTER_DIR_ENV)}
        self.env.update(HOME=str(self.home), AGENTKIT_SESSION="acme")

    def seat(self, model):
        config.save_session(config.load(), "acme", model, [model])

    def stop(self, hook, *tasks):
        """That hook hears the seat's Stop handing over `tasks`: the Stop it recorded, or None."""
        payload = {"hook_event_name": "Stop", "background_tasks": list(tasks),
                   "transcript_path": "", "last_assistant_message": "Started it."}
        done = subprocess.run(["bash", str(REPO / "hooks" / hook)], input=json.dumps(payload),
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        fact = config.hook_facts_path("acme")
        return json.loads(fact.read_text()) if fact.exists() else None

    def test_a_nudged_stop_records_the_work_it_hands_over(self):
        self.seat("mimo")
        fact = self.stop("seat-state.sh", SUBAGENT, SHELL)
        self.assertEqual((fact["event"], fact["kind"], fact["holds"]),
                         ("Stop", "background", ["subagent", "shell"]))

    def test_a_nudged_stop_handing_over_nothing_holds_nothing(self):
        self.seat("mimo")
        self.stop("seat-state.sh", SUBAGENT, SHELL)
        fact = self.stop("seat-state.sh")
        self.assertEqual((fact["event"], fact["kind"]), ("Stop", ""))
        self.assertNotIn("holds", fact)

    def test_a_nudged_stop_written_late_never_replaces_a_prompt_heard_after_it(self):
        # the prompt arrives while the Stop's writer starts: the Stop is the older fact
        self.seat("mimo")
        shim = self.home / "bin/python3"
        shim.parent.mkdir()
        shim.write_text(f"""#!/bin/bash
if [[ ${{2-}} == *lifecycle.stop_fact* && -n ${{PROMPT_FIRST-}} ]]; then
  PROMPT_FIRST= bash {REPO / "hooks/seat-state.sh"} \\
    <<<'{{"hook_event_name": "UserPromptSubmit", "prompt": "go on with acme"}}'
fi
exec {sys.executable} "$@"
""")
        shim.chmod(0o755)
        self.env.update(PATH=f"{shim.parent}{os.pathsep}{self.env['PATH']}", PROMPT_FIRST="1")
        self.assertEqual(self.stop("seat-state.sh", SUBAGENT)["event"], "UserPromptSubmit")

    def test_a_claude_stop_is_written_by_the_stop_hook_alone(self):
        self.seat("opus")
        self.assertIsNone(self.stop("seat-state.sh", SUBAGENT, SHELL))
        fact = self.stop("orchestrator-stop.sh", SUBAGENT, SHELL)
        self.assertEqual((fact["event"], fact["kind"], fact["holds"]),
                         ("Stop", "background", ["subagent", "shell"]))


if __name__ == "__main__":
    unittest.main()
