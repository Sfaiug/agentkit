"""A fresh headless turn of Codex or Muse runs with its harness's own approvals off.

The owner, 25 Nov 2026: every harness ak launches runs in bypass permission mode.  A turn asks
no one, so a harness waiting on an approval would hang it.  Offline: `adapters/<harness>.sh run`
starts a fake of that harness alone, first on PATH, which writes down each call's arguments and
what it read; after it on PATH come the system's own programs, each linked but the host's
`codex` and `muse`, and HOME is temporary, so no real harness runs.
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM

REPO = Path(__file__).resolve().parents[1]
PROMPT = "fix the api\n"
# The fake's own words, run by this interpreter: one JSON line per call to the file it is given.
RECORD = """import json, sys
with open(sys.argv[1], "a") as log:
    log.write(json.dumps({"args": sys.argv[2:], "stdin": sys.stdin.read()}) + "\\n")
"""


class HeadlessTurnsKeepTheirBypassFlag(unittest.TestCase):
    def options(self, harness):
        """The options of the one call of a fresh turn that carries the prompt, on its stdin or
        by its file's name: its arguments before any `--`."""
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-bypass-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        fakes, tools = root / "fakes", root / "tools"
        for folder in (fakes, tools, root / "acme"):
            folder.mkdir()
        log, fake, prompt = root / "calls", fakes / harness, root / "prompt.md"
        record = shlex.join([sys.executable, "-c", RECORD, str(log)])
        fake.write_text(f'#!/bin/sh\nexec {record} "$@"\n')
        fake.chmod(0o755)
        prompt.write_text(PROMPT)
        # Linked one by one, the first of a name as PATH would find it: a directory holding a
        # harness of the host's still lends the adapter its tools.
        for folder in SYSTEM:
            for program in Path(folder).glob("*"):
                link = tools / program.name
                if program.name not in ("codex", "muse") and not link.is_symlink():
                    link.symlink_to(program)
        proc = subprocess.run(
            ["bash", str(REPO / "adapters" / f"{harness}.sh"), "run", "acme-model", "high",
             str(root / "acme"), str(prompt), str(root / "out")],
            env={"HOME": str(root), "PATH": f"{fakes}{os.pathsep}{tools}"},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
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
