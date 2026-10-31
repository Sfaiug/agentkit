"""`adapters/<harness>.sh lend <home>` copies a login nothing can renew and says when it lapses.

A turn on a rented machine reads its login from that copy.  Renewing a subscription login
retires the one before it, so the copy is the login with every refresh token taken out,
owner-only, where a turn run with HOME=<home> reads it, and the original stays as it was.  The
verb prints the epoch second the copy lapses, read from the login's own expiry in each form
the harness writes it.  A login that has lapsed, holds no access token or is missing is none to
lend: exit 1, and nothing written under <home>.  With `own` and an account named, the copy of
that account's login goes where a turn naming the account reads it, as ak's live check runs it;
without `own`, where one naming none reads it, as a machine turn runs it.

Black-box: the adapters beside the program `AK_BIN` names, as tests/fixtures/hookdrive.py finds
them, run in a Home of tests/fixtures/akbin.py holding each case's login.  Go's login reading
answers to this key.  This test fails against `/bin/false`.
"""

import itertools
import json
from pathlib import Path
import stat
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

ENDS = 4102444800       # 2100-01-01T00:00:00Z
INSTANT = 4096892172    # 2099-10-28T17:36:12Z
LAPSED = 946684800      # 2000-01-01T00:00:00Z

# Each harness's login: where it keeps it under HOME, and where an account `acme` keeps its own;
# the login around an access token and its expiry, a refresh token beside them; each form a live
# expiry takes, with the epoch second it reads as; and a lapsed one.
LOGINS = {
    "claude": dict(
        path=".claude/.credentials.json", acme=".claude-acme/.credentials.json",
        login=lambda token, expiry: {"claudeAiOauth": {
            "accessToken": token, "refreshToken": "fixture-refresh", "expiresAt": expiry,
            "scopes": ["user:inference"], "subscriptionType": "max"}},
        # Claude Code's milliseconds, a fraction of a second over, and seconds
        live=[(ENDS * 1000 + 250, ENDS), (ENDS, ENDS)],
        lapsed=LAPSED * 1000),
    "grokbuild": dict(
        path=".grok/auth.json", acme=".grok-acme/auth.json",
        login=lambda token, expiry: {"https://auth.x.ai::fixture": {
            "key": token, "auth_mode": "oidc", "refresh_token": "fixture-refresh",
            "expires_at": expiry, "email": "owner@acme.test"}},
        live=[(form, INSTANT) for form in (
            "2099-10-28T17:36:12Z", "2099-10-28T17:36:12.123456789Z",
            "2099-10-28T12:36:12-05:00", "2099-10-28T23:06:12.5+05:30")],
        lapsed="2000-01-01T00:00:00Z"),
}


def renewless(login):
    """The login with every refresh token taken out."""
    return {name: renewless(value) if isinstance(value, dict) else value
            for name, value in login.items() if name not in ("refreshToken", "refresh_token")}


class Lend(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        # macOS's Keychain, which no HOME hides, holds no login here
        self.home.fake("security", "#!/bin/sh\nexit 1\n")
        self.homes = itertools.count()

    def lend(self, harness, login, *own, account=""):
        """Lend `account`'s login from the Home holding `login` where it keeps it, None for none,
        into an empty <home> of its own: what the verb did, and that <home>."""
        path = LOGINS[harness][account or "path"]
        (self.home.path / path).unlink(missing_ok=True)
        if login is not None:
            self.home.write(path, login)
        lent = self.home.root / f"lent-{next(self.homes)}"
        lent.mkdir()
        done = self.home.run("bash", str(ROOT / "adapters" / f"{harness}.sh"), "lend", str(lent),
                             *own, env={"AGENTKIT_ACCOUNT": account})
        return done, lent

    def test_a_live_login_is_copied_with_no_refresh_token_and_its_lapse_printed(self):
        for harness, spec in LOGINS.items():
            for expiry, ends in spec["live"]:
                with self.subTest(harness=harness, expiry=expiry):
                    login = spec["login"]("fixture-access", expiry)
                    done, lent = self.lend(harness, login)
                    self.assertEqual((done.code, done.out.strip()), (0, str(ends)), done.err)
                    copy = lent / spec["path"]
                    self.assertEqual(json.loads(copy.read_text()), renewless(login))
                    self.assertEqual(stat.S_IMODE(copy.stat().st_mode) & 0o077, 0)
                    original = self.home.path / spec["path"]
                    self.assertEqual(json.loads(original.read_text()), login)

    def test_a_login_lapsed_without_an_access_token_or_missing_is_none_to_lend(self):
        for harness, spec in LOGINS.items():
            live = spec["live"][0][0]
            for case, login in (("lapsed", spec["login"]("fixture-access", spec["lapsed"])),
                                ("blank", spec["login"]("", live)),
                                ("null", spec["login"](None, live)), ("missing", None)):
                with self.subTest(harness=harness, case=case):
                    done, lent = self.lend(harness, login)
                    self.assertEqual(done.code, 1, done.err)
                    self.assertEqual(list(lent.iterdir()), [])

    def test_own_puts_a_named_account_s_copy_where_a_turn_naming_it_reads_it(self):
        for harness, spec in LOGINS.items():
            login = spec["login"]("fixture-access", spec["live"][0][0])
            for own, place in ((("own",), spec["acme"]), ((), spec["path"])):
                with self.subTest(harness=harness, own=own):
                    done, lent = self.lend(harness, login, *own, account="acme")
                    self.assertEqual(done.code, 0, done.err)
                    self.assertEqual([path.relative_to(lent) for path in lent.rglob("*")
                                      if path.is_file()], [Path(place)])
                    self.assertEqual(json.loads((lent / place).read_text()), renewless(login))


if __name__ == "__main__":
    unittest.main()
