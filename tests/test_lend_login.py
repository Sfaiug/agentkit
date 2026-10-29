"""`adapters/<harness>.sh lend <home>` lends a copy of this host's login that cannot renew it.

Renewing a subscription login retires the one before it: on 28 Oct a check renewed the host's
Claude login in its throwaway HOME, and every seat held a dead one.  So for each harness whose
renewal retires the login, the copy goes where a turn run with HOME=<home> reads it, 0600,
holds no renewal secret, leaves the original as it was, and says when it stops authenticating.
The real adapters run on a temporary HOME holding fixture logins of fake values, with a fake of
every harness program, recording any call, and of macOS's Keychain, so no real login is reached.
"""

import base64
from datetime import datetime, timezone
import itertools
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[1]
ENDS = 4102444800     # 2100-01-01: when the fixture key stops authenticating
LAPSED = 946684800    # 2000-01-01: when a lapsed one did
INSTANT = int(datetime(2099, 10, 28, 17, 36, 12, tzinfo=timezone.utc).timestamp())


def jwt(claims):
    """A token in a JWT's shape, holding those claims and no real signature."""
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"fixture.{body}.signature"


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def without(entry, secret):
    return {name: value for name, value in entry.items() if name != secret}


def codex_lent(login, copy):
    """Codex's login, its refresh token wherever it keeps tokens the copy's nonblank placeholder:
    without one codex sends no credentials at all."""
    if "tokens" not in login:
        return login
    held = copy["tokens"]["refresh_token"]
    return {**login, "tokens": {**login["tokens"], "refresh_token": held if held.strip() else None}}


# Each harness's login as it keeps it: the file under HOME, the one an account `second` keeps,
# the login around a key and its expiry, and the copy lent of it.  Every renewal secret holds
# `fixture-refresh`, so a copy holding that word holds one.
LOGINS = {
    "claude": dict(
        usual=".claude/.credentials.json", second=".claude-second/.credentials.json",
        login=lambda key, ends: {
            "claudeAiOauth": {"accessToken": key, "refreshToken": "fixture-refresh",
                              "expiresAt": ends * 1000, "subscriptionType": "max"},
            "mcpOAuth": {"acme": {"accessToken": "fixture-mcp",
                                  "refreshToken": "fixture-refresh-mcp"}}},
        lent=lambda login, copy: {"claudeAiOauth": without(login["claudeAiOauth"],
                                                           "refreshToken")}),
    "codex": dict(
        usual=".codex/auth.json", second=".codex-second/auth.json",
        login=lambda key, ends: {
            "OPENAI_API_KEY": None, "last_refresh": "2026-10-28T17:36:12Z",
            "tokens": {"id_token": jwt({"email": "owner@acme.test"}), "access_token": key,
                       "refresh_token": "fixture-refresh", "account_id": "acme"}},
        lent=codex_lent),
    "grokbuild": dict(
        usual=".grok/auth.json", second=".grok-second/auth.json",
        login=lambda key, ends: {"https://auth.x.ai::fixture": {
            "key": key, "auth_mode": "oidc", "refresh_token": "fixture-refresh",
            "expires_at": iso(ends), "email": "owner@acme.test"}},
        lent=lambda login, copy: {name: without(entry, "refresh_token")
                                  for name, entry in login.items()}),
}


class Lend(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.homes = itertools.count()
        # every harness program a manifest names, recording any call, and macOS's Keychain,
        # which no HOME hides and which holds no login here
        fakes = self.root / "bin"
        fakes.mkdir()
        self.ran = self.root / "ran"
        for path in (REPO / "adapters").glob("*.toml"):
            program = fakes / tomllib.loads(path.read_text())["update"]["version"][0]
            program.write_text(f'#!/bin/sh\necho "$0 $*" >>"{self.ran}"\nexit 97\n')
            program.chmod(0o755)
        (fakes / "security").write_text("#!/bin/sh\nexit 1\n")
        (fakes / "security").chmod(0o755)
        self.path = f"{fakes}{os.pathsep}{os.environ['PATH']}"

    def write(self, harness, which, login):
        path = self.home / LOGINS[harness][which]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(login))
        return path

    def fixture(self, harness, which="usual", account="", key=None, ends=ENDS):
        """That harness's fixture login in the file `which` names, a key of its own."""
        key = jwt({"exp": ends, "sub": f"{harness}-{account}"}) if key is None else key
        login = LOGINS[harness]["login"](key, ends)
        return self.write(harness, which, login), login

    def lend(self, harness, account="", home=None):
        """Lend into `home`, by default a fresh one that does not exist yet."""
        home = home or self.root / f"lent-{next(self.homes)}"
        env = {"HOME": str(self.home), "PATH": self.path, "AGENTKIT_ACCOUNT": account}
        proc = subprocess.run(["bash", str(REPO / f"adapters/{harness}.sh"), "lend", str(home)],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertFalse(self.ran.exists(), f"{harness} ran a harness program to lend")
        return proc, home

    def assert_none(self, proc, home):
        """No login to lend: exit 1, one line saying so, and nothing written."""
        self.assertEqual((proc.returncode, proc.stdout), (1, ""))
        self.assertEqual(len(proc.stderr.splitlines()), 1, proc.stderr)
        self.assertFalse(home.exists())

    def assert_lent(self, harness, proc, home, login, ends):
        # the expiry alone on stdout and nothing on stderr, so no token reaches either
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr),
                         (0, "" if ends is None else f"{ends}\n", ""))
        dest = home / LOGINS[harness]["usual"]
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)
        self.assertNotIn("fixture-refresh", dest.read_text())
        copy = json.loads(dest.read_text())
        self.assertEqual(copy, LOGINS[harness]["lent"](login, copy))

    def test_a_copy_of_the_login_that_cannot_renew_it(self):
        # the usual login, then an account's own beside it
        for account, which, ends in (("", "usual", ENDS), ("second", "second", ENDS + 6)):
            for harness in LOGINS:
                with self.subTest(harness=harness, account=account):
                    original, login = self.fixture(harness, which, account, ends=ends)
                    before = original.read_bytes()
                    self.assert_lent(harness, *self.lend(harness, account), login, ends)
                    self.assertEqual(original.read_bytes(), before)

    def test_no_login_a_blank_key_and_a_lapsed_one_are_none_to_lend(self):
        for harness in LOGINS:
            with self.subTest(harness=harness):
                self.assert_none(*self.lend(harness))
                self.fixture(harness, key="")
                self.assert_none(*self.lend(harness))
                self.fixture(harness, ends=LAPSED)
                self.assert_none(*self.lend(harness))

    def test_this_home_and_a_taken_place_are_refused(self):
        for harness, spec in LOGINS.items():
            usual = Path(spec["usual"])
            # this HOME, where the usual login's place is empty while an account is lent
            for account, which in (("second", "second"), ("", "usual")):
                with self.subTest(harness=harness, account=account):
                    original, _ = self.fixture(harness, which, account)
                    before = original.read_bytes(), original.stat().st_ino
                    proc, _ = self.lend(harness, account, home=self.home)
                    self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr)
                    self.assertEqual((original.read_bytes(), original.stat().st_ino), before)
                    if account:
                        self.assertFalse((self.home / usual).exists())
            # another HOME whose folder is this one's: the copy's place is the login itself
            with self.subTest(harness=harness, taken=True):
                original, _ = self.fixture(harness)
                before = original.read_bytes(), original.stat().st_ino
                home = self.root / f"taken-{harness}"
                home.mkdir()
                (home / usual.parent).symlink_to(self.home / usual.parent)
                proc, _ = self.lend(harness, home=home)
                self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr)
                self.assertEqual((original.read_bytes(), original.stat().st_ino), before)

    def test_a_codex_api_key_is_lent_as_it_is(self):
        for tokens in ({}, {"tokens": {"access_token": "", "refresh_token": "fixture-refresh"}}):
            with self.subTest(tokens=tokens):
                login = {"auth_mode": "apikey", "OPENAI_API_KEY": "fixture-api-key", **tokens}
                self.write("codex", "usual", login)
                self.assert_lent("codex", *self.lend("codex"), login, None)

    def test_a_grok_expiry_reads_in_every_iso_8601_form(self):
        for form in ("2099-10-28T17:36:12Z", "2099-10-28T17:36:12.25Z",
                     "2099-10-28T12:36:12-05:00", "2099-10-28T23:06:12+0530"):
            with self.subTest(form=form):
                login = {"https://auth.x.ai::fixture": {"key": "fixture-key", "expires_at": form}}
                self.write("grokbuild", "usual", login)
                self.assert_lent("grokbuild", *self.lend("grokbuild"), login, INSTANT)


if __name__ == "__main__":
    unittest.main()
