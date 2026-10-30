"""ak's live check holds only copies of logins that cannot renew, and writes nothing back.

Through smoke_home's own code and agentkit/lend.py, from a caller HOME of fixture logins, Grok's
lapsed, with every harness program, and macOS's Keychain, faked: OpenCode's answers that it
merges no other config document and saved no login, every other answers nothing.
"""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import lend

SMOKE = (REPO / "tests/smoke.sh").read_text()
MANIFESTS = {path.stem: tomllib.loads(path.read_text())
             for path in sorted((REPO / "adapters").glob("*.toml"))}
ENDS = 4102444800       # 2100-01-01: when the first login lent stops authenticating
TOKEN = "fixture." + base64.urlsafe_b64encode(json.dumps({"exp": ENDS}).encode()).decode() + ".sig"
OPENCODE = """case "$*" in "api --standalone config.get"|"auth export --standalone") echo '[]'; exit 0 ;; esac
"""

# Each login as the caller keeps it, every renewal secret `fixture-refresh`.
LOGINS = {
    ".claude/.credentials.json": {"claudeAiOauth": {"accessToken": "fixture-access",
        "refreshToken": "fixture-refresh", "expiresAt": (ENDS + 60) * 1000}},
    ".codex/auth.json": {"tokens": {"access_token": TOKEN, "refresh_token": "fixture-refresh"}},
    ".grok/auth.json": {"fixture": {"key": "fixture-key", "refresh_token": "fixture-refresh",
                                    "expires_at": "2000-01-01T00:00:00Z"}},
    ".grok/auth.json.lock": "",
    ".config/muse/auth.json": {"providers": {"meta": {"api_key": "fixture-key"}}},
    ".gemini/antigravity-cli/antigravity-oauth-token": {"token": {"refresh_token": "fixture-key"}},
    ".config/opencode/opencode.json": {"provider": {"mimo": {"options": {"apiKey": "fixture-key"}}}},
    ".local/share/opencode/auth.json": {"mimo": {"type": "api", "key": "fixture-key"}},
}
LENT = {".claude/.credentials.json", ".codex/auth.json", ".config/muse/auth.json",
        ".gemini/antigravity-cli/antigravity-oauth-token", ".config/opencode/opencode.json"}


class ChecksLendLoginsThatCannotRenew(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-lend-checks-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.caller = self.root / "caller"
        for name, login in LOGINS.items():
            path = self.caller / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(login if isinstance(login, str) else json.dumps(login))
        self.before = {path: path.read_bytes() for path in self.caller.rglob("*") if path.is_file()}
        fakes = self.root / "bin"
        fakes.mkdir()
        for name, data in [*MANIFESTS.items(), ("keychain", {"update": {"version": ["security"]}})]:
            program = fakes / data["update"]["version"][0]
            program.write_text("#!/bin/sh\n" + (OPENCODE if name == "opencode" else "") + "exit 97\n")
            program.chmod(0o755)
        self.env = {"PATH": f"{fakes}:{os.environ['PATH']}", "HOME": str(self.caller),
                    "REPO": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"}

    def assert_lent_copies(self, home):
        """Every login a manifest lists is a lent copy there or absent, nothing there links to
        the caller's logins, and the caller's are as they were."""
        logins = {self.caller / name for name in LOGINS}
        self.assertFalse({path.resolve() for path in home.rglob("*") if path.is_symlink()} & logins)
        listed = {entry[2:] for data in MANIFESTS.values()
                  for entry in data.get("worker", {}).get("logins", [])
                  if entry.startswith("~/") and "$" not in entry}
        for name in listed | LENT:
            with self.subTest(home=home.name, login=name):
                path = home / name
                self.assertEqual(path.is_file() and not path.is_symlink(), name in LENT)
                if name in LENT:
                    self.assertEqual(path.stat().st_nlink, 1)
                    self.assertNotIn("fixture-refresh", path.read_text())
        self.assertEqual({path: path.read_bytes() for path in self.before}, self.before)

    def test_the_smoke_home_holds_copies_that_cannot_renew(self):
        setup = SMOKE[SMOKE.index("smoke_share_probes() {"):SMOKE.index("# A bounded way")]
        result = subprocess.run(["/bin/bash", "-c", setup + "\nsmoke_home\n"],
                                env={**self.env, "WORK": str(self.root / "smoke")},
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_lent_copies(self.root / "smoke/home")

    def test_the_module_returns_when_the_first_login_it_lent_lapses(self):
        home, taken = self.root / "lent", self.root / "taken/.config/opencode/opencode.json"
        taken.parent.mkdir(parents=True)
        taken.write_text("{}")      # OpenCode's, lent last: none lent before it is left
        with patch.dict(os.environ, self.env, clear=True):
            self.assertRaises(FileExistsError, lend.into, self.root / "taken")
            lent, ends = lend.into(home)
        self.assertEqual([path for path in taken.parents[2].rglob("*") if path.is_file()], [taken])
        self.assertEqual(ends, ENDS)    # Codex's; Claude's is a minute later, Grok's lapsed
        self.assertEqual({str(path.relative_to(home)) for files in lent.values() for path in files},
                         LENT)
        self.assert_lent_copies(home)


if __name__ == "__main__":
    unittest.main()
