"""The fresh-install gate's workers can read the agentkit copy in its throwaway HOME.

Every worker box gets an empty /tmp of its own, and step f's executor and reviewer run that
copy's adapters: a HOME under /tmp left them `No such file or directory`.  Offline: the gate
runs only as far as its first shell in the throwaway HOME, which a stub `bash` on that shell's
PATH answers by writing the HOME down and failing; a box built as a turn's then reads an
adapter there.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import box

# The caller's own: lent to the throwaway HOME, or naming where the gate looks for logins.
CALLER = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME", "GROK_BIN_DIR", "OPENCODE_CONFIG",
          "OPENCODE_CONFIG_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "GH_CONFIG_DIR",
          "GH_TOKEN", "GITHUB_TOKEN")


class GateHome(unittest.TestCase):
    def test_a_worker_box_reads_the_gate_s_agentkit_copy(self):
        # A caller's home is never under /tmp; the test's stands where a real one would.
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-e2e-reach-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        caller = Path(tmp.name)
        seen, stubs = caller / "seen-home", caller / "stubs"
        # The caller's `gh auth token` lends a token; the gate's shells in the throwaway HOME
        # look in the caller's ~/.local/bin before the system's.
        for stub, text in ((stubs / "gh", "echo fixture-token\n"),
                           (caller / ".local/bin/bash", f'printf %s "$HOME" >"{seen}"\nexit 1\n')):
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text(f"#!/bin/sh\n{text}")
            stub.chmod(0o755)
        env = {key: value for key, value in os.environ.items()
               if key not in CALLER and not key.startswith(("AK_", "AGENTKIT_"))}
        env.update(HOME=str(caller), PATH=f"{stubs}:{env.get('PATH', '/usr/bin:/bin')}")
        gate = subprocess.run(["bash", str(REPO / "tests/e2e-fresh.sh")], env=env, cwd=caller,
                              capture_output=True, text=True, timeout=300)
        self.assertTrue(seen.is_file(), gate.stdout + gate.stderr)
        home = Path(seen.read_text())
        self.assertTrue(home.is_absolute(), home)
        # The gate took its workdir with it on the way out; put back what step f clones.
        self.addCleanup(shutil.rmtree, home.parent, ignore_errors=True)
        adapter = home / "agentkit/adapters/codex.sh"
        adapter.parent.mkdir(parents=True)
        adapter.write_text("#!/bin/sh\n")
        workspace, out = home / ".agentkit/wt/acme", home / ".agentkit/runs/fix-api/out"
        workspace.mkdir(parents=True)
        out.mkdir(parents=True)
        with account_home(caller), box.command(["test", "-r", str(adapter)],
                                               {**os.environ, "HOME": str(home)}, out,
                                               cwd=workspace) as (cmd, turn_env, spawn):
            spawn.pop("stop")
            turn = subprocess.run(cmd, env=turn_env, cwd=workspace, capture_output=True,
                                  text=True, timeout=60, **spawn)
        self.assertEqual(box.returncode(out, turn.returncode), 0,
                         f"{adapter} is not readable in a worker box\n{turn.stderr}")


if __name__ == "__main__":
    unittest.main()
