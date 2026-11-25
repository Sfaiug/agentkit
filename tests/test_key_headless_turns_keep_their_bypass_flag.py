"""A fresh headless turn of Codex or Muse runs with its harness's own approvals off.

The owner, 25 Nov 2026: every harness ak launches runs in bypass permission mode.  A turn asks
no one, so a harness waiting on an approval would hang it.  Offline: `adapters/<harness>.sh run`
starts a fake of that harness alone, first on PATH, which writes down each call's arguments and
what it read; the rest of PATH is the system's own directories, less any holding the host's
`codex` or `muse`, and HOME is temporary, so no real harness runs.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM

REPO = Path(__file__).resolve().parents[1]
PROMPT = "fix the api\n"
FAKE = """#!{python}
import json, sys
with open({log!r}, "a") as log:
    log.write(json.dumps({{"args": sys.argv[1:], "stdin": sys.stdin.read()}}) + "\\n")
"""


class HeadlessTurnsKeepTheirBypassFlag(unittest.TestCase):
    def options(self, harness):
        """The options of the one call of a fresh turn that carries the prompt, on its stdin or
        by its file's name: its arguments before any `--`."""
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-bypass-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "bin").mkdir()
        (root / "acme").mkdir()
        log, fake, prompt = root / "calls", root / "bin" / harness, root / "prompt.md"
        fake.write_text(FAKE.format(python=sys.executable, log=str(log)))
        fake.chmod(0o755)
        prompt.write_text(PROMPT)
        path = [str(root / "bin"), *(d for d in SYSTEM if not any(
            os.path.exists(os.path.join(d, h)) for h in ("codex", "muse")))]
        proc = subprocess.run(
            ["bash", str(REPO / "adapters" / f"{harness}.sh"), "run", "acme-model", "high",
             str(root / "acme"), str(prompt), str(root / "out")],
            env={"HOME": str(root), "PATH": os.pathsep.join(path)}, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        carrying = [call["args"] for call in calls
                    if call["stdin"] == PROMPT or str(prompt) in call["args"]]
        self.assertEqual(len(carrying), 1, calls)
        args = carrying[0]
        return args[:args.index("--")] if "--" in args else args

    def assertRuns(self, options, *runs):
        for run in runs:
            self.assertTrue(any(options[at:at + len(run)] == run for at in range(len(options))),
                            f"{run} not among {options}")

    def test_a_codex_turn_bypasses_approvals_and_sandbox(self):
        self.assertRuns(self.options("codex"), ["--dangerously-bypass-approvals-and-sandbox"])

    def test_a_muse_turn_runs_yolo_with_its_approval_judge_off(self):
        self.assertRuns(self.options("muse"), ["--yolo"], ["--approval-judge", "off"])


if __name__ == "__main__":
    unittest.main()
