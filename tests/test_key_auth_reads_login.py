"""A harness's `auth` says whether a turn can sign in, and `auth seat` whether the seat can.

ak asks a harness's adapter `auth` before every turn and `auth seat` about a seat's own login,
and reads the exit code, 0 yes or 1 no, and the one line printed on either stream, which the
owner sees.  Claude Code keeps two logins that expire apart, the seat's and a long-lived worker
token, so `auth seat` reads the seat's alone; Grok Build keeps one, and `seat` asks the same.
A lapsed login that can be renewed gets a turn of the harness where only a turn renews it.

Black-box: the adapters beside the program `AK_BIN` names (or `AK_ROOT`'s) run as ak runs them,
in a throwaway HOME holding each case's login files, with a fake of the harness first on PATH
that writes down each start; this test fails against `/bin/false`.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import combinations_with_replacement
import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, Home
from fixtures.hookdrive import ROOT

DAY = 86400
EMAIL = "acme@example.com"
CREDS = ".claude/.credentials.json"
TOKEN = ".agentkit/secrets/claude_oauth_token"
AUTH = ".grok/auth.json"
REFUSED = ".agentkit/state/grok-refused"
# Where Claude Code writes down whose its login is.
WHO = {".claude.json": {"oauthAccount": {"emailAddress": EMAIL}}}
LAPSED, FRESH = 1_000_000_000_000, 4_102_444_800_000      # 2001 and 2100, in milliseconds
EARLIER, LATER = "2001-09-09T01:46:40Z", "2100-01-01T00:00:00Z"
VERBS = (("auth",), ("auth", "seat"))
# Each harness's program, and the login a turn of it renews.
PROGRAM = {"claude": ("claude", CREDS), "grokbuild": ("grok", AUTH)}
# A start of the harness: written down, held a second so that an ask made at once arrives
# while it runs, and leaving the login `renewed` beside HOME holds, where the case has one.
TURN = LOG + 'sleep 1\n[ ! -e {renewed} ] || cp {renewed} "$HOME"/{login}\n'
# No Keychain: on a Mac the adapter would read the owner's own login there.
NO_KEYCHAIN = "#!/bin/sh\nexit 1\n"

VALID = f"claude: the OAuth token in ~/{CREDS} is still valid"
EXPIRED = f"claude: the OAuth token in ~/{CREDS} expired; run /login"
NO_LOGIN = (1, f"claude: no OAuth credentials in ~/{CREDS} and no CLAUDE_CODE_OAUTH_TOKEN; "
               "run /login")
SAVED = f"grok: the login in ~/{AUTH} is saved"


def oauth(expires, **more):
    """A Claude Code login as it keeps one."""
    return {"claudeAiOauth": {"accessToken": "acme-seat", "expiresAt": expires, **more}}


def session(expires, **more):
    """A Grok Build login as it keeps one."""
    return {"https://auth.x.ai::acme": {"key": "acme-key", "auth_mode": "oidc",
                                        "expires_at": expires, **more}}


def hence(hours, offset):
    """The instant `hours` from now, written `offset` hours from UTC."""
    at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)
    return at.astimezone(timezone(timedelta(hours=offset))).isoformat()


def digest(key):
    """What Grok's `usage` writes down of a key the billing endpoint refused."""
    return hashlib.sha256(key.encode()).hexdigest() + "\n"


def ask(home, harness, verb, env):
    """The verb's exit code and the lines it printed on either stream, as ak reads them."""
    done = home.run(str(ROOT / "adapters" / f"{harness}.sh"), *verb, input="", env=env)
    return done.code, [line.strip() for line in (done.out + done.err).splitlines() if line.strip()]


class AuthReadsLogin(unittest.TestCase):
    def reads(self, harness, files, auth, seat=None, *, env=None, renewed=None, turns=0,
              asked=VERBS):
        """In a Home holding `files` (a (data, seconds ago) pair back-dates one), the verbs
        `asked` at once answer: `auth` with `auth`, `auth seat` with `seat` (`auth`'s when None),
        each a code and a line with ~ for HOME; and the harness was started `turns` times."""
        with Home() as home:
            program, login = PROGRAM[harness]
            home.fake("security", NO_KEYCHAIN)
            home.fake(program, TURN.format(
                python=shlex.quote(sys.executable), log=shlex.quote(str(home.log(program))),
                renewed=shlex.quote(str(home.root / "renewed")), login=login))
            if renewed is not None:
                (home.root / "renewed").write_text(json.dumps(renewed))
            for path, data in files.items():
                data, ago = data if isinstance(data, tuple) else (data, None)
                home.write(path, data, ago=ago)
            with ThreadPoolExecutor(len(asked)) as pool:
                said = list(pool.map(lambda verb: ask(home, harness, verb, env), asked))
            answer = {verb: (code, [line.replace("~/", f"{home.path}/")])
                      for verb, (code, line) in zip(VERBS, (auth, seat or auth))}
            self.assertEqual(said, [answer[verb] for verb in asked])
            self.assertEqual(len(home.calls(program)), turns)

    # Claude Code

    def test_claude_a_credential_in_the_environment_answers_for_a_turn_never_the_seat(self):
        self.reads("claude", WHO, (0, "claude: CLAUDE_CODE_OAUTH_TOKEN is set"), NO_LOGIN,
                   env={"CLAUDE_CODE_OAUTH_TOKEN": "acme-env"})

    def test_claude_a_worker_token_inside_its_year_answers_for_a_turn_never_the_seat(self):
        self.reads("claude", {**WHO, TOKEN: ("acme-worker\n", 100.5 * DAY)},
                   (0, f"claude: long-lived worker token in ~/{TOKEN} (expires in 264 days); "
                       f"logged in as {EMAIL}"), NO_LOGIN)

    def test_claude_a_worker_token_past_its_year_is_a_no(self):
        self.reads("claude", {**WHO, TOKEN: ("acme-worker\n", 366 * DAY)},
                   (1, "claude: worker token expired; run `claude setup-token` and replace "
                       f"~/{TOKEN}"), NO_LOGIN)

    def test_claude_a_live_login_says_whose_where_claude_code_wrote_it_down(self):
        live = {CREDS: oauth(FRESH, refreshToken="acme-refresh")}
        self.reads("claude", {**WHO, **live}, (0, f"{VALID}; logged in as {EMAIL}"))
        self.reads("claude", live, (0, VALID))

    def test_claude_a_lapsed_login_gets_one_turn_and_is_read_as_it_left_it(self):
        lapsed = {**WHO, CREDS: oauth(LAPSED, refreshToken="acme-refresh")}
        # Each pair in a Home of its own: in one crowd, whichever verb reaches a lock first
        # could keep the others from racing each other.
        for pair in combinations_with_replacement(VERBS, 2):
            self.reads("claude", lapsed, (0, f"{VALID}; logged in as {EMAIL}"),
                       renewed=oauth(FRESH, refreshToken="acme-refresh-2"), turns=1, asked=pair)
        # asked alone, and its turn renews nothing: it is read as still lapsed
        for verb in VERBS:
            self.reads("claude", lapsed, (1, EXPIRED), asked=(verb,), turns=1)

    def test_claude_an_expired_login_with_nothing_to_renew_it_is_a_no(self):
        self.reads("claude", {**WHO, CREDS: oauth(LAPSED)}, (1, EXPIRED))

    def test_claude_no_login_is_a_no(self):
        self.reads("claude", WHO, NO_LOGIN)

    def test_claude_a_login_that_is_not_json_is_a_no(self):
        self.reads("claude", {**WHO, CREDS: '{"claudeAiOauth": {"accessToken": "acme-seat", '},
                   (1, f"claude: the credentials in ~/{CREDS} carry no access token; "
                       "run /login"))

    # Grok Build

    def test_grok_a_credential_in_the_environment_answers(self):
        self.reads("grokbuild", {}, (0, "grok: XAI_API_KEY is set"),
                   env={"XAI_API_KEY": "acme-api-key"})

    def test_grok_a_live_login_answers(self):
        # an hour ahead written five hours behind UTC, whose text sorts before now's
        for expires in (LATER, hence(1, -5)):
            with self.subTest(expires=expires):
                self.reads("grokbuild", {AUTH: session(expires)}, (0, SAVED))

    def test_grok_a_lapsed_login_holding_a_refresh_token_answers_without_a_turn(self):
        # grok renews its own key whenever it runs
        self.reads("grokbuild", {AUTH: session(EARLIER, refresh_token="acme-refresh")},
                   (0, f"{SAVED}; grok renews its lapsed key itself"))

    def test_grok_an_expired_login_with_nothing_to_renew_it_is_a_no(self):
        # an hour ago written five hours ahead of UTC, whose text sorts after now's
        for expires in (EARLIER, hence(-1, 5)):
            with self.subTest(expires=expires):
                self.reads("grokbuild", {AUTH: session(expires)},
                           (1, f"grok: the login in ~/{AUTH} is expired; run `grok login`"))

    def test_grok_no_login_is_a_no(self):
        self.reads("grokbuild", {}, (1, f"grok: no ~/{AUTH}; run `grok login`"))

    def test_grok_a_login_that_is_not_json_is_a_no(self):
        self.reads("grokbuild", {AUTH: '{"https://auth.x.ai::acme": {"key": "acme-key", '},
                   (1, f"grok: ~/{AUTH} is not JSON; run `grok login`"))

    def test_grok_a_login_whose_key_the_billing_endpoint_refused_is_a_no(self):
        self.reads("grokbuild", {AUTH: session(LATER), REFUSED: digest("acme-key")},
                   (1, f"grok: the billing endpoint refused the login in ~/{AUTH} after grok's "
                       "own renewal; run `grok login`"))
        # a login saved since holds another key
        self.reads("grokbuild", {AUTH: session(LATER), REFUSED: digest("acme-old-key")},
                   (0, SAVED))


if __name__ == "__main__":
    unittest.main()
