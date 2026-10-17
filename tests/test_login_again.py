"""`login again` signs in afresh over a login that still stands, which `login` leaves: each
adapter for real on a temporary HOME, its harness a fake on PATH writing down its arguments."""

import json, os, pty, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# adapter -> (its harness's program, where the saved login lives, the sign-in it runs)
HARNESSES = {"claude.sh": ("claude", ".claude/.credentials.json", ["auth", "login"]),
             "codex.sh": ("codex", ".codex/auth.json", ["login", "--device-auth"]),
             "grokbuild.sh": ("grok", ".grok/auth.json", ["login"]),
             "muse.sh": ("muse", ".config/muse/auth.json", ["login"])}


class LoginAgain(unittest.TestCase):
    def login(self, adapter, *args):
        """The adapter's `login` at a terminal over a saved login, and each call of its harness."""
        program, saved, _ = HARNESSES[adapter]
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            (home / "bin").mkdir()
            for name, text in ((program, """#!/bin/sh\njq -nc '$ARGS.positional' --args -- "$@" >>"$HOME/calls"\n"""),
                               ("security", "#!/bin/sh\nexit 1\n")):    # no Keychain login
                (home / "bin" / name).write_text(text)
                (home / "bin" / name).chmod(0o755)
            (home / saved).parent.mkdir(parents=True)
            (home / saved).write_text('{"accessToken": "a", "tokens": {"access_token": "a"}}')
            primary, secondary = pty.openpty()
            try:
                proc = subprocess.run(["bash", str(REPO / "adapters" / adapter), "login", *args],
                                      stdin=secondary, capture_output=True, text=True, timeout=30,
                                      env={"HOME": str(home), "TERM": "dumb",
                                           "PATH": f"{home / 'bin'}:{os.environ['PATH']}"})
            finally:
                os.close(primary)
                os.close(secondary)
            calls = home / "calls"
            return proc, [json.loads(c) for c in calls.read_text().splitlines()] if calls.exists() else []

    def test_login_leaves_a_login_that_stands_and_again_signs_in_over_it(self):
        for adapter, (*_, sign_in) in HARNESSES.items():
            with self.subTest(adapter):
                proc, calls = self.login(adapter)
                self.assertEqual((proc.returncode, calls), (0, []), proc.stderr)
                self.assertIn("already logged in", proc.stdout)
                proc, calls = self.login(adapter, "again")
                self.assertEqual((proc.returncode, calls), (0, [sign_in]), proc.stderr)


if __name__ == "__main__":
    unittest.main()
