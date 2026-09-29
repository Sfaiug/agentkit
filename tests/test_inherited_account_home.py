"""A call on the usual login never uses the account home a seat handed down; offline.

A seat on a named subscription runs with that subscription's login home in its environment --
CLAUDE_CONFIG_DIR=~/.claude-<name>, CODEX_HOME=~/.codex-<name>, GROK_HOME=~/.grok-<name> -- and
everything it starts inherits it, while AGENTKIT_ACCOUNT is dropped for a call meant for the
usual login.  Each adapter drops such a home when no account is named, keeps a home the user
set anywhere else, and still hands a named account its own.  A fake harness on PATH records
the home it was given, and HOME is temporary, so no real login or subscription is reached.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]

# The home each harness would log in from: its variable, else its default under HOME
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
var = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME", "grok": "GROK_HOME"}[name]
sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(os.environ.get(var) or str(Path.home() / f".{name}"))
print(json.dumps({"type": "result", "result": "ok", "session_id": "sid-1"}))
'''

# adapter, the harness it starts, the variable it hands its login home in
HARNESSES = (("claude.sh", "claude", "CLAUDE_CONFIG_DIR"),
             ("codex.sh", "codex", "CODEX_HOME"),
             ("grokbuild.sh", "grok", "GROK_HOME"))


class InheritedAccountHome(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="inherited-home-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        fake = self.root / "fake"
        fake.mkdir()
        for _, name, _ in HARNESSES:
            (fake / name).write_text(FAKE)
            (fake / name).chmod(0o755)
        self.log = self.root / "home-used"
        self.prompt = self.root / "prompt.md"
        self.prompt.write_text("go\n")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("AK_", "AGENTKIT_"))
                    and k not in [var for _, _, var in HARNESSES]}
        self.env.update(HOME=str(self.root), PATH=f"{fake}:{os.environ['PATH']}",
                        FAKE_LOG=str(self.log))

    def home_used(self, adapter, account, **inherited):
        """The login home a turn through `adapter` reached, with `inherited` in its env."""
        self.log.unlink(missing_ok=True)
        env = dict(self.env, AGENTKIT_ACCOUNT=account, **inherited)
        proc = subprocess.run(["bash", str(REPO / "adapters" / adapter), "run", "default",
                               "high", str(self.root), str(self.prompt), str(self.root / "out")],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return self.log.read_text()

    def test_an_inherited_account_home_with_no_account_named_reaches_the_usual_login(self):
        for adapter, name, var in HARNESSES:
            with self.subTest(adapter=adapter):
                self.assertEqual(self.home_used(adapter, "",
                                                **{var: f"{self.root}/.{name}-second"}),
                                 f"{self.root}/.{name}")

    def test_a_home_the_user_set_elsewhere_is_kept(self):
        for adapter, name, var in HARNESSES:
            with self.subTest(adapter=adapter):
                own = f"{self.root}/own/.{name}"
                self.assertEqual(self.home_used(adapter, "", **{var: own}), own)

    def test_a_named_account_still_gets_its_own_home(self):
        for adapter, name, var in HARNESSES:
            with self.subTest(adapter=adapter):
                self.assertEqual(self.home_used(adapter, "third",
                                                **{var: f"{self.root}/.{name}-second"}),
                                 f"{self.root}/.{name}-third")


if __name__ == "__main__":
    unittest.main()
