"""A second Muse subscription keeps its own login in every verb.

`[providers.meta] accounts` lists the subscriptions; ak names one to adapters/muse.sh in
AGENTKIT_ACCOUNT.  The real adapter is run against a fake `muse` on PATH that writes down the
login it read -- `$XDG_CONFIG_HOME/muse/auth.json`, where Muse Code keeps it -- and HOME is
temporary, so no real login, session or endpoint is reached.  An account reads and writes its
own login under ~/.muse-<name> and its own state files; the usual login reads and writes only
today's.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, usage  # noqa: E402
from agentkit.harness import muse  # noqa: E402

# One JSON line per call: the login it read and the session it opened or resumed.  A key with a
# `refuse-<key>` file is refused as a spent subscription is, in Muse's own words.  `login` saves a
# key where Muse would.  Sessions live under XDG_DATA_HOME, as Muse's do.
FAKE_MUSE = r"""#!/usr/bin/env bash
auth="${XDG_CONFIG_HOME:-$HOME/.config}/muse/auth.json"
sessions="${XDG_DATA_HOME:-$HOME/.local/share}/muse/sessions"
key=$(jq -r '.providers.meta.api_key // empty' "$auth" 2>/dev/null)
sid=""; prev=""
for a in "$@"; do [ "$prev" = --session-id ] && sid=$a; prev=$a; done
resumed=false; [ -n "$sid" ] && [ -d "$sessions/$sid" ] && resumed=true
jq -nc --arg verb "${1:-}" --arg key "$key" --arg sid "$sid" --argjson resumed "$resumed" \
  '{verb: $verb, key: $key, config: $ENV.XDG_CONFIG_HOME, env_key: $ENV.META_API_KEY,
    resume: $sid, resumed: $resumed}' >>"$FAKE/muse-calls"
case "${1:-}" in
login)
  mkdir -p "${auth%/*}"
  printf '{"providers":{"meta":{"api_key":"minted"}}}\n' >"$auth" ;;
exec)
  sid=${sid:-s-$key}
  mkdir -p "$sessions/$sid"
  printf '{"stream":{"kind":"session","id":"%s"}}\n' "$sid"
  if [ -f "$FAKE/refuse-$key" ]; then
    echo "HTTP 429 subscription quota exhausted; resets at 2099-01-02T03:04:05Z" >&2
    exit 1
  fi
  printf '{"payload":{"kind":"run_terminal","text":"done on %s"}}\n' "$key" ;;
esac
"""

# Loaded by every Python child: no probe here may reach a network.
NO_NETWORK = """import http.client
def refuse(*a, **k):
    raise AssertionError("external network forbidden")
http.client.HTTPSConnection = refuse
"""

CONFIG = """[models.spark]
harness = "muse"
model = "muse-spark-1.3-contributor"
effort = "xhigh"
provider = "meta"

[providers.meta]
usage_model = "spark"
usage_effort = "minimal"
{accounts}
"""


class MuseAccounts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-muse-accounts-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        self.fake, bin, site = root / "fake", root / "bin", root / "site"
        for d in (self.fake, bin, site):
            d.mkdir()
        (bin / "muse").write_text(FAKE_MUSE)
        (bin / "muse").chmod(0o755)
        (site / "sitecustomize.py").write_text(NO_NETWORK)
        home = root / ".agentkit"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, key, home / key.lower()))
        self.stack.enter_context(patch.object(config, "HOME", home))
        # the usual login, and a key exported for it, which no account may ever spend
        self.usual = root / ".config/muse/auth.json"
        self.save_login(self.usual, "key-default")
        (root / ".config/gh").mkdir()
        (root / ".config/gh/hosts.yml").write_text("acme: {}\n")
        self.second = root / ".muse-second/muse/auth.json"
        self.save_login(self.second, "key-second")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("AGENTKIT_", "AK_", "XDG_", "MUSE_", "TBH_"))
               and k != "META_API_KEY"}
        env.update(HOME=str(root), PATH=f"{bin}{os.pathsep}{env.get('PATH', '')}",
                   FAKE=str(self.fake), PYTHONPATH=str(site), META_API_KEY="env-key",
                   AGENTKIT_SESSION="", AK_RUN_DEPTH="0", AK_MAX_RUNS="0",
                   AGENTKIT_DISCORD_WEBHOOK="off")
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        self.work = root / "work"
        self.work.mkdir()

    # --- the fixture ------------------------------------------------------

    def save_login(self, path, key):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"providers": {"meta": {"api_key": key}}}))

    def configure(self, accounts='accounts = ["default", "second"]'):
        (config.HOME / "config.toml").write_text(CONFIG.format(accounts=accounts))
        self.cfg = config.load()

    def adapter(self, *argv, account="", stdin=subprocess.DEVNULL, **env):
        return subprocess.run([str(REPO / "adapters/muse.sh"), *argv], stdin=stdin,
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, "AGENTKIT_ACCOUNT": account, **env})

    def turn(self, name, account="", session=None, **env):
        prompt = self.work / "prompt.md"
        prompt.write_text("Do the task.\n")
        out = self.root / "runs" / name
        proc = self.adapter("run", "muse-spark-1.3-contributor", "xhigh", str(self.work),
                            str(prompt), str(out), *([session] if session else []),
                            account=account, **env)
        muse.record_turn(out, config.STATE, account)
        return proc, (out / "session_id").read_text()

    def calls(self):
        try:
            text = (self.fake / "muse-calls").read_text()
        except OSError:
            return []
        return [json.loads(line) for line in text.splitlines()]

    def snapshot(self, *paths):
        return {path: (path.read_bytes(), path.stat().st_mtime_ns) if path.exists() else None
                for path in paths}

    def meters(self, used, **extra):
        return {"meters": [{"name": "window", "used": used, "resets_at": int(time.time()) + 3600,
                            "window_secs": 18000}], **extra}

    # --- run ----------------------------------------------------------------

    def test_a_turn_on_an_account_spends_its_own_login_and_resumes_on_the_usual(self):
        (self.fake / "refuse-key-second").touch()
        usual = self.snapshot(self.usual, config.STATE / "usage-meta.json")
        proc, session = self.turn("second", account="second")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        [call] = self.calls()
        self.assertEqual((call["key"], call["config"], call["env_key"]),
                         ("key-second", str(self.root / ".muse-second"), None))
        # its refusal is its own record; the usual login's files are as they were
        record = json.loads((config.STATE / "usage-meta.second.json").read_text())
        self.assertEqual(record["meters"][0]["used"], 100)
        self.assertEqual(self.snapshot(self.usual, config.STATE / "usage-meta.json"), usual)
        # every other program a turn starts reads the usual config home through it
        self.assertEqual((self.root / ".muse-second/gh").resolve(),
                         (self.root / ".config/gh").resolve())

        # the conversation begun there resumes on the usual login, and a seat's config home
        # handed down to a call naming no account is dropped rather than spent
        proc, again = self.turn("default", session=session,
                                XDG_CONFIG_HOME=str(self.root / ".muse-second"))
        self.assertEqual((proc.returncode, again), (0, session), proc.stderr)
        call = self.calls()[-1]
        self.assertEqual((call["key"], call["config"], call["env_key"], call["resumed"]),
                         ("key-default", None, "env-key", True))
        self.assertFalse((config.STATE / "usage-meta.json").exists())

        # the usual login's refusal is today's record, and leaves the account's alone
        (self.fake / "refuse-key-default").touch()
        second = self.snapshot(config.STATE / "usage-meta.second.json", self.second)
        proc, _ = self.turn("usual")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads((config.STATE / "usage-meta.json").read_text())["meters"][0]
                         ["used"], 100)
        self.assertEqual(self.snapshot(config.STATE / "usage-meta.second.json", self.second),
                         second)

    # --- auth and login -----------------------------------------------------

    def test_auth_and_login_answer_for_the_account_s_own_home(self):
        usual = self.snapshot(self.usual)
        # the usual login is saved and a key is exported for it: neither is this account's
        proc = self.adapter("auth", account="third")
        self.assertEqual(proc.returncode, 1)
        self.assertIn(str(self.root / ".muse-third/muse/auth.json"), proc.stderr)
        self.assertIn(f"XDG_CONFIG_HOME={self.root / '.muse-third'} muse login", proc.stderr)
        proc = self.adapter("login", account="third")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.calls(), [])

        leader, follower = os.openpty()
        self.addCleanup(os.close, leader)
        try:
            proc = self.adapter("login", account="third", stdin=follower)
        finally:
            os.close(follower)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads((self.root / ".muse-third/muse/auth.json").read_text())
                         ["providers"]["meta"]["api_key"], "minted")
        [call] = self.calls()
        self.assertEqual((call["verb"], call["config"], call["env_key"]),
                         ("login", str(self.root / ".muse-third"), None))
        self.assertEqual(self.snapshot(self.usual), usual)
        proc = self.adapter("auth", account="third")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(str(self.root / ".muse-third/muse/auth.json"), proc.stdout)

        # the usual login answers exactly as it always did
        proc = self.adapter("auth")
        self.assertEqual((proc.returncode, proc.stdout), (0, "muse: META_API_KEY is set\n"))
        proc = self.adapter("auth", META_API_KEY="")
        self.assertEqual((proc.returncode, proc.stdout.strip()),
                         (0, f"muse: the login in {self.usual} is saved"))

    # --- interactive ----------------------------------------------------------

    def test_a_seat_on_an_account_is_launched_on_its_login(self):
        proc = self.adapter("interactive", "muse-spark-1.3-contributor", "xhigh", "sid-1",
                            account="second")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cmd = shlex.split(proc.stdout)
        self.assertEqual(cmd[:4], ["env", "-u", "META_API_KEY",
                                   f"XDG_CONFIG_HOME={self.root / '.muse-second'}"])
        self.assertIn("resume", cmd)
        # the usual login's seat is launched as it always was
        proc = self.adapter("interactive", "muse-spark-1.3-contributor", "xhigh", "sid-1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cmd = shlex.split(proc.stdout)
        self.assertEqual(cmd[cmd.index("env") + 1], "MUSE_NO_AUTO_UPDATE=1")
        self.assertFalse(any("XDG_CONFIG_HOME" in arg or arg == "-u" for arg in cmd))

    # --- usage ----------------------------------------------------------------

    def test_usage_reads_each_login_s_own_record_and_cache(self):
        self.configure()
        spent = self.meters(100)
        (config.STATE / "usage-meta.json").write_text(json.dumps(spent))
        (config.STATE / "usage-meta-probe.json").write_text(
            json.dumps({"provider": "meta", "error": None, "fetched_at": time.time(),
                        **self.meters(50)}))
        (config.STATE / "usage-meta.second-probe.json").write_text(
            json.dumps({"provider": "meta", "error": None, "fetched_at": time.time() - 60,
                        **self.meters(30)}))
        proc = self.adapter("usage", account="second")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual((data["meters"][0]["used"], data["account"], data["error"]),
                         (30, "second", None))
        # an account with no login of its own is not logged in, whatever the usual login has
        proc = self.adapter("usage", account="third")
        self.assertEqual(json.loads(proc.stdout)["error"],
                         "unknown: not logged in: Muse auth file is missing")
        # the usual login reads today's record, and its answer names no account
        self.assertEqual(json.loads(self.adapter("usage").stdout), spent)
        self.assertEqual(self.calls(), [])

        # and `ak usage` rows: the usual login's refusal is its own row's, so the turn moves on
        providers = usage.collect(self.cfg)
        accounts = providers["meta"]["accounts"]
        self.assertTrue(accounts["default"]["exhausted"])
        self.assertFalse(accounts["second"]["exhausted"])
        self.assertEqual(accounts["second"]["meters"][0]["used"], 30)
        self.assertEqual(providers["meta"]["account"], "second")

    def test_a_reading_is_dated_and_a_record_applied_from_its_own_login_s_files(self):
        self.configure(accounts="")
        stamp = time.time() - 900
        reading = {"provider": "meta", "error": None, **self.meters(40)}
        (config.STATE / "usage-meta-probe.json").write_text(
            json.dumps({**reading, "fetched_at": time.time()}))
        (config.STATE / "usage-meta.second-probe.json").write_text(
            json.dumps({**reading, "fetched_at": stamp}))
        out = {"fetched_at": None}
        muse.usage_extra(out, {**reading, "account": "second"}, config.STATE)
        self.assertEqual(out["fetched_at"], stamp)
        out = {"fetched_at": None}
        muse.usage_extra(out, reading, config.STATE)
        self.assertNotEqual(out["fetched_at"], stamp)

        # with no accounts the usual login's record is every read's, at once, as today ...
        spent = self.meters(100)
        (config.STATE / "usage-meta.json").write_text(json.dumps(spent))
        self.assertEqual(muse.usage_recorded(config.STATE, time.time()), spent["meters"])
        # ... and with accounts no row is handed another login's
        self.configure()
        self.assertEqual(muse.usage_recorded(config.STATE, time.time()), [])


if __name__ == "__main__":
    unittest.main()
