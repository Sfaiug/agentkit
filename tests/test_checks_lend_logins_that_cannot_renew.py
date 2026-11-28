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
# Where agy keeps the answers to its first-run pages, beside its usual login, and a caller's.
ANSWERS = ".gemini/antigravity-cli/cache/onboarding.json"
ANSWERED = '{"onboardingComplete": true}'


class LentLogins(unittest.TestCase):
    """The caller HOME and faked programs, and what a HOME lent from them holds."""

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


class ChecksLendLoginsThatCannotRenew(LentLogins):
    def test_the_smoke_home_holds_copies_that_cannot_renew(self):
        code, said, _ = self.smoke_home("smoke")
        self.assertEqual(code, 0, said)
        self.assert_lent_copies(self.root / "smoke/home")

    def answer_agy(self):
        """The caller answers agy's first-run pages on its usual login.  Another profile,
        which no check runs agy on, holds broken answers: nothing reads them."""
        (self.caller / ANSWERS).parent.mkdir()
        (self.caller / ANSWERS).write_text(ANSWERED)
        other = self.caller / ".gemini/antigravity-cli-acme/cache/onboarding.json"
        other.parent.mkdir(parents=True)
        other.symlink_to("gone.json")

    def smoke_home(self, work, **env):
        """smoke_home's exit building the suite `work`'s home, what it said, and the first-run
        answers that home holds."""
        setup = SMOKE[SMOKE.index("smoke_share_probes() {"):SMOKE.index("# A bounded way")]
        result = subprocess.run(["/bin/bash", "-c", setup + "\nsmoke_home\n"],
                                env={**self.env, **env, "WORK": str(self.root / work)},
                                text=True, capture_output=True, timeout=120)
        home = self.root / work / "home"
        return (result.returncode, result.stdout + result.stderr,
                {str(path.relative_to(home)): path.read_text()
                 for path in home.rglob("onboarding.json")})

    def test_the_smoke_home_holds_agys_first_run_answers_for_each_of_its_logins(self):
        self.answer_agy()
        # The token lent is a login, and a key the suite inherits is one too: agy signs in on
        # the usual login with either.
        code, said, held = self.smoke_home("token")
        self.assertEqual((code, held), (0, {ANSWERS: ANSWERED}), said)
        (self.caller / ".gemini/antigravity-cli/antigravity-oauth-token").unlink()
        code, said, held = self.smoke_home("key", GEMINI_API_KEY="fixture-key")
        self.assertEqual((code, held), (0, {ANSWERS: ANSWERED}), said)

    def test_agys_first_run_answers_are_read_only_where_its_seat_can_open(self):
        self.answer_agy()
        cache, fakes = (self.caller / ANSWERS).parent, self.root / "bin"
        cache.chmod(0)
        self.addCleanup(cache.chmod, 0o700)
        # Out of reach, the answers of a seat the checks can open are there and broken, never
        # absent: they end the suite.
        code, said, _ = self.smoke_home("unreached")
        self.assertEqual(code, 1, said)
        self.assertIn(f"cannot read {self.caller / ANSWERS}", said)
        # Check 3a's home is for Claude's check alone, here one that passes: no agy seat opens
        # in it.
        stream = SMOKE[SMOKE.index("smoke_share_probes() {"):SMOKE.index("usage_fresh_check() {")]
        passes = ('python3() { case $1 in */check_claude_stream.py) ;; '
                  '*) command python3 "$@" ;; esac; }\n')
        result = subprocess.run(["/bin/bash", "-c", passes + stream, "smoke.sh",
                                 "--claude-stream", str(self.root / "stream")],
                                env={**self.env, "TMPDIR": str(self.root)},
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Signed out, agy opens no seat here,
        (self.caller / ".gemini/antigravity-cli/antigravity-oauth-token").unlink()
        code, said, held = self.smoke_home("signed-out")
        self.assertEqual((code, held), (0, {}), said)
        # nor does a host without agy, whatever key the suite inherits.
        (fakes / "agy").unlink()
        code, said, held = self.smoke_home("no-agy", PATH=f"{fakes}:/usr/bin:/bin",
                                           GEMINI_API_KEY="fixture-key")
        self.assertEqual((code, held), (0, {}), said)

    def test_the_module_returns_when_the_first_login_it_lent_lapses(self):
        home, taken = self.root / "lent", self.root / "taken/.config/opencode/opencode.json"
        taken.parent.mkdir(parents=True)
        taken.write_text("{}")      # OpenCode's, lent last: none lent before it is left
        with patch.dict(os.environ, self.env, clear=True):
            self.assertRaises(FileExistsError, lend.into, self.root / "taken")
            lent, ends = lend.into(home)
        self.assertEqual([path for path in taken.parents[2].rglob("*") if path.is_file()], [taken])
        self.assertEqual(ends, (ENDS, "codex"))     # Claude's is a minute later, Grok's lapsed
        self.assertEqual({str(path.relative_to(home)) for files in lent.values() for path in files},
                         LENT)
        self.assert_lent_copies(home)


if __name__ == "__main__":
    unittest.main()
