"""ak knows when each subscription's login ends, and whose it is.

Claude's adapter reads the day its login stops serving (`refreshTokenExpiresAt`, which no
renewal moves) and the account's email; the tick keeps every subscription's answer in
`state/logins.json`, asking each at most hourly and at once when told to, and one made again
on the ak screen as it finishes, one writer at a time.  The real
`adapters/claude.sh` on a temporary HOME, and a fake adapter for the rest: no real login.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, logins

FAR = 1000 + 30 * 86400      # a login further off than a week: its meter is grey

# A fake adapter: counts its calls in $FAKE/calls and answers for the account it was named,
# or fails for one named in $FAKE/fail, or for one named in $FAKE/hang leaves a reader behind
# that holds its output, whose pid is $FAKE/reader.  Where $FAKE/interrupt exists that reader
# interrupts its caller a second later, once it awaits the answer: an interrupt that lands
# while Popen still starts the adapter loses its pid with it.
FAKE_ADAPTER = r"""#!/usr/bin/env bash
[ "$1" = login-end ] || exit 2
account=${AGENTKIT_ACCOUNT:-default}
echo "$account" >>"$FAKE/calls"
[ ! -e "$FAKE/fail-$account" ] || exit 1
[ ! -e "$FAKE/hang-$account" ] || (CALLER=$PPID sh -c 'echo $$ >"$FAKE/reader"
    [ ! -e "$FAKE/interrupt" ] || { sleep 1; kill -INT "$CALLER"; }; exec sleep 30' &)
cat "$FAKE/answer-$account"
"""


class ClaudeAdapter(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        # macOS keeps the login in the Keychain, which no HOME hides: this `security` finds none
        self.bin = self.home / "bin"
        self.bin.mkdir()
        (self.bin / "security").write_text("#!/usr/bin/env bash\nexit 1\n")
        (self.bin / "security").chmod(0o755)

    def login_end(self, account=""):
        proc = subprocess.run(["bash", str(REPO / "adapters/claude.sh"), "login-end"],
                              capture_output=True, text=True, timeout=30,
                              env={"HOME": str(self.home), "AGENTKIT_ACCOUNT": account,
                                   "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def login(self, directory, ends, email, profile):
        (self.home / directory).mkdir(parents=True, exist_ok=True)
        (self.home / directory / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "a", "refreshToken": "r", "expiresAt": 1,
            "refreshTokenExpiresAt": ends}}))
        profile.write_text(json.dumps({"oauthAccount": {"emailAddress": email}}))

    def test_a_login_says_the_second_its_refresh_token_ends_and_whose_it_is(self):
        self.login(".claude", 1792470143000, "owner@acme.test", self.home / ".claude.json")
        self.assertEqual(self.login_end(), {"email": "owner@acme.test", "ends": 1792470143})

    def test_b_a_named_account_answers_from_its_own_directory(self):
        self.login(".claude", 1792470143000, "owner@acme.test", self.home / ".claude.json")
        self.login(".claude-second", 1792986467000, "two@acme.test",
                   self.home / ".claude-second/.claude.json")
        self.assertEqual(self.login_end("second"), {"email": "two@acme.test", "ends": 1792986467})

    def test_c_no_login_is_nobody_with_no_end(self):
        self.assertEqual(self.login_end(), {"email": None, "ends": None})


class Refresh(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.fake = root / "fake"
        adapters = root / "adapters"
        self.fake.mkdir()
        adapters.mkdir()
        (adapters / "claude.sh").write_text(FAKE_ADAPTER)
        (adapters / "claude.sh").chmod(0o755)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            patcher = patch.object(config, name, root / name.lower())
            patcher.start()
            self.addCleanup(patcher.stop)
        # whatever the tick's pass pages goes nowhere, whatever webhook is set
        env = patch.dict(os.environ, {"FAKE": str(self.fake), config.ADAPTER_DIR_ENV: str(adapters),
                                      "AK_NOTIFY_SINK": "off"})
        env.start()
        self.addCleanup(env.stop)
        self.cfg = {"providers": {"anthropic": {"accounts": ["default", "second"]}},
                    "models": {"opus": {"harness": "claude", "provider": "anthropic"}}}
        self.answer("default", {"email": "owner@acme.test", "ends": FAR})
        self.answer("second", {"email": "two@acme.test", "ends": None})

    def answer(self, account, value):
        (self.fake / f"answer-{account}").write_text(json.dumps(value))

    def calls(self):
        path = self.fake / "calls"
        return path.read_text().split() if path.exists() else []

    def test_a_every_subscription_is_kept_with_its_email_and_end(self):
        logins.refresh(self.cfg, now=1000)
        self.assertEqual(logins.read(), {"anthropic": {
            "default": {"email": "owner@acme.test", "ends": FAR, "checked_at": 1000},
            "second": {"email": "two@acme.test", "ends": None, "checked_at": 1000}}})

    def test_b_each_is_asked_hourly_at_most_and_one_whose_meter_is_amber_every_tick(self):
        soon = {"email": "owner@acme.test", "ends": 1000 + 86400}
        self.answer("default", soon)
        logins.refresh(self.cfg, now=1000)
        logins.refresh(self.cfg, now=1001)
        self.assertEqual(self.calls(), ["default", "second", "default"])
        self.answer("default", {**soon, "ends": FAR})    # logged in again from the ak screen
        self.assertEqual(logins.refresh(self.cfg, now=1002)["anthropic"]["default"]["ends"], FAR)
        logins.refresh(self.cfg, now=1000 + logins.ASK_EVERY - 1)     # grey again: hourly
        self.assertEqual(self.calls()[3:], ["default"])
        logins.refresh(self.cfg, now=1000 + logins.ASK_EVERY)
        self.assertEqual(self.calls()[4:], ["second"])

    def test_c_an_adapter_that_answers_nothing_leaves_its_last_answer_and_waits_an_hour(self):
        logins.refresh(self.cfg, now=1000)
        (self.fake / "fail-default").touch()
        self.answer("second", {"email": "two@acme.test", "ends": "soon"})
        later = 1000 + logins.ASK_EVERY
        kept = logins.refresh(self.cfg, now=later)
        self.assertEqual(kept["anthropic"]["default"],
                         {"email": "owner@acme.test", "ends": FAR, "checked_at": later})
        self.assertEqual(kept["anthropic"]["second"],
                         {"email": "two@acme.test", "ends": None, "checked_at": later})
        logins.refresh(self.cfg, now=later + 1)
        self.assertEqual(self.calls(), ["default", "second"] * 2)

    def test_d_a_subscription_the_config_no_longer_lists_is_dropped(self):
        logins.refresh(self.cfg, now=1000)
        self.cfg["providers"]["anthropic"]["accounts"] = ["default"]
        self.assertEqual(list(logins.refresh(self.cfg, now=1001)["anthropic"]), ["default"])

    def test_f_a_provider_whose_models_were_removed_is_asked_through_its_shipped_harness(self):
        logins.refresh(self.cfg, now=1000)
        self.cfg["models"] = {}
        self.answer("default", {"email": "owner@acme.test", "ends": FAR + 1})
        kept = logins.refresh(self.cfg, now=1000 + logins.ASK_EVERY)
        self.assertEqual(kept["anthropic"]["default"]["ends"], FAR + 1)
        self.assertEqual(kept["anthropic"]["second"]["email"], "two@acme.test")
        # one no harness names keeps what it last said
        self.cfg["providers"]["acme"] = {}
        config._write_json(logins.path(),
                           {**kept, "acme": {"default": {"ends": FAR, "checked_at": 0}}})
        later = 1000 + 2 * logins.ASK_EVERY
        self.assertEqual(logins.refresh(self.cfg, now=later)["acme"],
                         {"default": {"ends": FAR, "checked_at": later}})

    def hang(self):
        """The default account's adapter leaves a reader that this process adopts, orphaned."""
        import ctypes
        self.assertEqual(ctypes.CDLL(None).prctl(36, 1, 0, 0, 0), 0)  # PR_SET_CHILD_SUBREAPER
        (self.fake / "hang-default").touch()

    def reader_outlived_the_ask(self):
        reader = int((self.fake / "reader").read_text())
        try:
            alive = os.waitpid(reader, os.WNOHANG)[0] == 0   # orphaned, it is this process's child
        except ChildProcessError:
            return False    # the ask reaped it
        if alive:
            os.kill(reader, signal.SIGKILL)
            os.waitpid(reader, 0)
        return alive

    @unittest.skipUnless(sys.platform == "linux", "a subreaper sees the reader left behind")
    def test_g_an_ask_that_hangs_leaves_none_of_its_readers_running(self):
        self.hang()
        with patch.object(logins, "ASK_TIMEOUT", 1):
            kept = logins.refresh(self.cfg, now=1000)
        self.assertEqual(kept["anthropic"]["default"], {"checked_at": 1000})
        self.assertFalse(self.reader_outlived_the_ask())

    @unittest.skipUnless(sys.platform == "linux", "a subreaper sees the reader left behind")
    def test_h_an_interrupted_ask_leaves_none_of_its_readers_running(self):
        self.hang()
        (self.fake / "interrupt").touch()
        with self.assertRaises(KeyboardInterrupt):
            logins.refresh(self.cfg, now=1000)
        self.assertFalse(self.reader_outlived_the_ask())

    def test_i_a_login_renewed_while_the_tick_asks_waits_for_it_and_stands(self):
        soon = {"email": "owner@acme.test", "ends": 1000 + 86400}
        self.answer("default", soon)
        logins.refresh(self.cfg, now=1000)                  # amber: the next tick asks it
        self.cfg["providers"]["anthropic"]["accounts"] = ["default"]   # and drops second
        tick_asks, release, asked, ask = threading.Event(), threading.Event(), [], logins._ask

        def asking(harness, account):
            asked.append((threading.current_thread().name, account))
            if threading.current_thread().name == "tick":
                answer = ask(harness, account)          # from before the login
                tick_asks.set()
                release.wait(10)
                return answer
            return ask(harness, account)
        with patch.object(logins, "_ask", side_effect=asking):
            tick = threading.Thread(target=logins.refresh, args=(self.cfg, 1001), name="tick")
            tick.start()
            self.assertTrue(tick_asks.wait(10))
            self.answer("default", {**soon, "ends": FAR})   # the ak screen's login finished
            renew = threading.Thread(target=logins.renewed, name="renew",
                                     args=(self.cfg, "anthropic", "default", 1002))
            renew.start()
            renew.join(0.5)               # time enough to ask, were it not waiting for the tick
            release.set()
            tick.join(10)
            renew.join(10)
        self.assertEqual(asked, [("tick", "default"), ("renew", "default")])
        self.assertEqual(logins.read(), {"anthropic": {"default": {
            "email": "owner@acme.test", "ends": FAR, "checked_at": 1002}}})

    def test_j_a_renewed_login_that_answers_nothing_writes_nothing(self):
        logins.refresh(self.cfg, now=1000)
        before = logins.read()
        (self.fake / "fail-default").touch()
        logins.renewed(self.cfg, "anthropic", "default", now=1001)
        self.assertEqual(logins.read(), before)

    def test_e_the_tick_keeps_them(self):
        from agentkit import watch
        passes = {what: run for what, run, _ in watch.local_passes({}, False, print)}
        with patch.object(config, "load", return_value=self.cfg):
            passes["the login-end read did not run"]()
        self.assertEqual(sorted(logins.read()["anthropic"]), ["default", "second"])


if __name__ == "__main__":
    unittest.main()
