"""A failed prompt-context callback must not leave the Stop guard without a turn.

The context reader inspects the real records before it fails. No sleep or scheduler timing
decides the result; the question fact must still stand until its context has been read.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class PromptTurn(unittest.TestCase):
    def test_context_failure_still_leaves_a_turn_and_preserves_answer_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".agentkit/state"
            state.mkdir(parents=True)
            previous = {"session": "acme", "event": "PreToolUse",
                        "kind": "request_user_input", "at": 1}
            (state / "hook-acme.json").write_text(json.dumps(previous))
            scripts = root / "bin"
            scripts.mkdir()
            python = scripts / "python3"
            python.write_text('''#!/bin/bash
if [[ $1 = -c && $2 = *"from agentkit import orch"* ]]; then
  "$TEST_PYTHON" - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ["HOME"])
state = root / ".agentkit/state"
seen = {name: json.loads((state / name).read_text())
        for name in ("stop-acme.json", "hook-acme.json") if (state / name).exists()}
(root / "before-context.json").write_text(json.dumps(seen))
PY
  exit 42
fi
exec "$TEST_PYTHON" "$@"
''')
            python.chmod(0o755)
            done = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")],
                input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Use v2"}),
                text=True, capture_output=True, timeout=30,
                env={"HOME": tmp, "PATH": f"{scripts}:{os.environ['PATH']}",
                     "TEST_PYTHON": sys.executable, "AGENTKIT_SESSION": "acme"})
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
            before = json.loads((root / "before-context.json").read_text())
            self.assertIn("stop-acme.json", before)
            turn = before["stop-acme.json"]
            self.assertEqual((turn["session"], turn["blocks"]), ("acme", 0))
            self.assertGreater(turn["turn"], 1)
            self.assertEqual(before["hook-acme.json"], previous)
            final = json.loads((state / "hook-acme.json").read_text())
            self.assertEqual((final["event"], final["at"]),
                             ("UserPromptSubmit", turn["turn"]))
            self.assertEqual(json.loads((state / "stop-acme.json").read_text()), turn)


if __name__ == "__main__":
    unittest.main()
