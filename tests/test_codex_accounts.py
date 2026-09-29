"""A named ChatGPT subscription serves every Codex verb from its own login; offline.

adapters/codex.sh is told the account in AGENTKIT_ACCOUNT.  A named one lives in ~/.codex-<name>
and nothing of the usual login -- ~/.codex/auth.json, OPENAI_API_KEY, CODEX_API_KEY -- answers
for it; with no account named, every verb uses ~/.codex as it always did.  Fake `codex` and
`curl` on PATH record the login each call used, and HOME is temporary, so no real login,
subscription or endpoint is reached.
"""

import json
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters/codex.sh"

# One JSON line per call: its arguments, the CODEX_HOME and keys it was handed, and the token
# of the login it read.  `login` signs in by writing a fresh auth.json where codex would.  A
# resume reads its thread from the sessions of the home it runs under.
FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
args = sys.argv[1:]
call = {"args": args, "home": os.environ.get("CODEX_HOME"),
        "keys": [os.environ.get("OPENAI_API_KEY"), os.environ.get("CODEX_API_KEY")]}
if "login" in args:
    (home / "auth.json").write_text('{"tokens":{"access_token":"tok-new"}}')
else:
    call["token"] = json.loads((home / "auth.json").read_text())["tokens"]["access_token"]
    if "resume" in args:
        call["resumed"] = (home / "sessions" / (args[args.index("resume") + 1] + ".jsonl")).read_text()
    sys.stdin.read()
    print(json.dumps({"type": "thread.started", "thread_id": "thread-2"}))
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(call) + "\n")
'''

# The bearer token out of the `-H @file` header, logged with the URL; every endpoint answers
# 200 the way chatgpt.com does, one reset credit in hand.
FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
header = open(next(a[1:] for a in args if a.startswith("@"))).read()
url = next(a for a in args if a.startswith("https://"))
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"url": url, "token": header.split("Bearer ")[1].split()[0]}) + "\n")
if url.endswith("/consume"):
    body = {"code": "reset"}
elif url.endswith("/rate-limit-reset-credits"):
    body = {"credits": [{"id": "credit-1", "status": "available"}]}
else:
    body = {"rate_limit": {"secondary_window": {"used_percent": 40, "reset_at": 4102444800,
                                                "limit_window_seconds": 604800}}}
sys.stdout.write(json.dumps(body) + "\n200")
'''

VALID = 4102444800000   # 2100, in milliseconds


class CodexAccounts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="codex-accounts-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.usual, self.second = self.root / ".codex", self.root / ".codex-second"
        for home, token in ((self.usual, "tok-default"), (self.second, "tok-second")):
            home.mkdir()
            self.login(home, token)
        for store in ("sessions", "archived_sessions"):
            (self.usual / store).mkdir()
        (self.usual / "config.toml").write_text('model = "test-model"\n')
        (self.usual / "sessions/thread-1.jsonl").write_text('{"begun":"on the usual login"}\n')
        fake = self.root / "fake"
        (fake / "bin").mkdir(parents=True)
        for name, text in (("codex", FAKE_CODEX), ("curl", FAKE_CURL)):
            (fake / "bin" / name).write_text(text)
            (fake / "bin" / name).chmod(0o755)
        self.log = fake / "calls"
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("AK_", "AGENTKIT_")) and k != "CODEX_HOME"}
        self.env.update(HOME=str(self.root), PATH=f"{fake / 'bin'}:{os.environ['PATH']}",
                        FAKE_LOG=str(self.log), OPENAI_API_KEY="test-key",
                        CODEX_API_KEY="test-exec-key")

    def login(self, home, token, expires=VALID):
        (home / "auth.json").write_text(json.dumps({"tokens": {
            "access_token": token, "account_id": f"id-{token}", "expires_at": expires}}))

    def adapter(self, account, *args, stdin=subprocess.DEVNULL):
        env = dict(self.env, AGENTKIT_ACCOUNT="" if account == "default" else account)
        if account != "default":
            env["CODEX_HOME"] = str(self.usual)   # inherited from a seat of the usual login
        self.log.unlink(missing_ok=True)
        proc = subprocess.run(["bash", str(ADAPTER), *args], env=env, stdin=stdin, cwd=self.root,
                              capture_output=True, text=True, timeout=60)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return proc, [json.loads(line) for line in calls]

    def tree(self, home):
        """Every entry of a home, with its bytes or where it links: what a verb may not change."""
        found = {}
        for path in sorted(home.rglob("*")):
            found[str(path.relative_to(home))] = (
                os.readlink(path) if path.is_symlink()
                else None if path.is_dir() else path.read_bytes())
        return found

    def each(self, verb):
        """Run `verb` on the named account and on the usual one; each leaves the other alone."""
        for account, own, other in (("second", self.second, self.usual),
                                    ("default", self.usual, self.second)):
            with self.subTest(account=account):
                before = self.tree(other)
                verb(account, own, "tok-" + account)
                self.assertEqual(self.tree(other), before)

    def test_run_uses_the_account_login_and_resumes_the_shared_conversation(self):
        def run(account, own, token):
            out = self.root / f"out-{account}"
            prompt = self.root / "prompt.md"
            prompt.write_text("go\n")
            for sid in ("", "thread-1"):
                proc, calls = self.adapter(account, "run", "default", "high", str(self.root),
                                           str(prompt), str(out), *([sid] if sid else []))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                [call] = calls
                self.assertEqual(call["token"], token)
                self.assertEqual((out / "session_id").read_text(), "thread-2")
                if sid:
                    self.assertEqual(call["resumed"], '{"begun":"on the usual login"}\n')
                if account == "default":
                    self.assertIsNone(call["home"])
                    self.assertEqual(call["keys"], ["test-key", "test-exec-key"])
                    self.assertNotIn('cli_auth_credentials_store="file"', call["args"])
                else:
                    self.assertEqual(call["home"], str(own))
                    self.assertEqual(call["keys"], [None, None])
                    self.assertIn('cli_auth_credentials_store="file"', call["args"])
        self.each(run)

    def test_meters_and_resets_are_read_and_spent_with_the_account_token(self):
        def meters(account, own, token):
            for verb, calls_made in (("usage", 1), ("reset-status", 2), ("reset", 4)):
                proc, calls = self.adapter(account, verb)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIsNone(json.loads(proc.stdout)["error"], proc.stdout)
                self.assertEqual([c["token"] for c in calls], [token] * calls_made, verb)
        self.each(meters)

    def test_auth_answers_about_the_account_login_alone(self):
        def auth(account, own, token):
            for seat in ([], ["seat"]):
                proc, _ = self.adapter(account, "auth", *seat)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn(str(own / "auth.json"), proc.stdout)
            self.login(own, token, expires=1)    # spent, while the other login is still good
            proc, _ = self.adapter(account, "auth")
            self.assertEqual(proc.returncode, 1)
            self.assertIn(str(own / "auth.json"), proc.stderr)
            self.login(own, token)
        self.each(auth)

    def test_login_signs_the_account_in_to_its_own_home(self):
        def login(account, own, token):
            proc, calls = self.adapter(account, "login")
            self.assertEqual((proc.returncode, proc.stdout), (0, "codex: already logged in\n"))
            self.assertEqual(calls, [])
            (own / "auth.json").unlink()
            primary, secondary = pty.openpty()
            try:
                proc, calls = self.adapter(account, "login", stdin=secondary)
            finally:
                os.close(primary)
                os.close(secondary)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            [call] = calls
            self.assertEqual(call["args"][-2:], ["login", "--device-auth"])
            self.assertEqual(json.loads((own / "auth.json").read_text()),
                             {"tokens": {"access_token": "tok-new"}})
            if account == "default":
                self.assertEqual((call["home"], call["args"]), (None, ["login", "--device-auth"]))
            else:
                self.assertEqual(call["home"], str(own))
                self.assertEqual(call["args"][:2], ["-c", 'cli_auth_credentials_store="file"'])
            self.login(own, token)
        self.each(login)

    def test_interactive_opens_the_seat_on_the_account_home(self):
        def interactive(account, own, token):
            proc, calls = self.adapter(account, "interactive", "default", "high")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(calls, [])
            prefix = f"env -u OPENAI_API_KEY -u CODEX_API_KEY CODEX_HOME={own} "
            self.assertEqual(proc.stdout.startswith(prefix), account != "default", proc.stdout)
            if account != "default":
                self.assertEqual((own / "sessions").resolve(), self.usual / "sessions")
                self.assertEqual((own / "config.toml").resolve(), self.usual / "config.toml")
        self.each(interactive)


if __name__ == "__main__":
    unittest.main()
