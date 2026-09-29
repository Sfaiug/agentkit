"""A second Grok subscription keeps its own login in every verb.

`[providers.xai] accounts` names the subscriptions, and ak names one to adapters/grokbuild.sh
in AGENTKIT_ACCOUNT.  A named account's login lives in ~/.grok-<name> and its refusal in a state
file of its own; with no account named the usual login is exactly today's, a GROK_HOME the user
set included.  Conversations are one store, so a conversation begun on either resumes on the
other.  A fake `grok` and a fake `curl` on PATH answer per home and per key, and HOME is
temporary, so no real login, endpoint or state is reached.
"""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config  # noqa: E402
from agentkit.harness import grokbuild  # noqa: E402

ADAPTER = REPO / "adapters/grokbuild.sh"
FIX = REPO / "tests/fixtures"
API_KEY = "fixture.api.not.a.token"

# One JSON line per call: its arguments and the home and API key it was given.  `login` writes
# $HOME/fake/login into its home; `models` writes `renewed-<home name>` over the home's
# auth.json, the way grok renews a lapsed key; a turn opens its conversation under the home's
# sessions/ the way grok does, and refuses to resume one that is not there.
FAKE_GROK = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
from urllib.parse import quote
fake = Path.home() / "fake"
home = Path(os.environ.get("GROK_HOME") or Path.home() / ".grok")
args = sys.argv[1:]
with open(fake / "grok-calls", "a") as fh:
    fh.write(json.dumps({"args": args, "home": os.environ.get("GROK_HOME"),
                         "key": os.environ.get("XAI_API_KEY")}) + "\\n")
if args[:1] == ["login"]:
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text((fake / "login").read_text())
elif args[:1] == ["models"]:
    renewed = fake / f"renewed-{home.name}"
    if renewed.exists():
        (home / "auth.json").write_text(renewed.read_text())
    print("  * grok-4.7 (default)")
elif "--prompt-file" in args:
    flag = "--resume" if "--resume" in args else "--session-id"
    sid = args[args.index(flag) + 1]
    conversation = home / "sessions" / quote(os.getcwd(), safe="") / sid
    if flag == "--resume" and not conversation.is_dir():
        sys.exit(f"no such session: {sid}")
    conversation.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"type": "result", "result": "ok", "session_id": sid}))
"""

# The bearer token out of the `-H @file` header, appended to $HOME/fake/asked, and the answer
# from `resp-<token>`, else `resp`, else 000: the code on the first line, the body on the rest.
FAKE_CURL = """#!/usr/bin/env bash
hf=""; prev=""
for a in "$@"; do
  if [ "$prev" = "-H" ]; then case "$a" in @*) hf=${a#@};; esac; fi
  prev=$a
done
tok=$(sed -n 's/^Authorization: Bearer //p' "$hf" 2>/dev/null | head -1)
printf '%s\\n' "$tok" >>"$HOME/fake/asked"
resp="$HOME/fake/resp-$tok"
[ -f "$resp" ] || resp="$HOME/fake/resp"
[ -f "$resp" ] || { printf '\\n000\\n'; exit 0; }
printf '%s\\n%s\\n' "$(sed -n '2,$p' "$resp")" "$(sed -n '1p' "$resp")"
"""


def token(name):
    return f"fixture.{name}.not.a.token"


def login(name, expires="2030-06-01T00:00:00Z", refresh=False):
    entry = {"key": token(name), "auth_mode": "oidc", "expires_at": expires}
    if refresh:
        entry["refresh_token"] = "fixture.refresh.not.a.token"
    return json.dumps({"https://auth.x.ai::fixture": entry})


class GrokAccounts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".grok-accounts-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.fake, self.work = self.home / "fake", self.home / "work"
        self.state = self.home / ".agentkit/state"
        bin_ = self.home / "bin"
        for directory in (self.fake, self.work, self.state, bin_):
            directory.mkdir(parents=True)
        for name, script in (("grok", FAKE_GROK), ("curl", FAKE_CURL)):
            (bin_ / name).write_text(script)
            (bin_ / name).chmod(0o755)
        # Both subscriptions are signed in, each with a key of its own, and an API key is
        # exported beside them: which one a verb uses is which one it was told to.
        self.usual, self.second = self.home / ".grok", self.home / ".grok-second"
        for home, name in ((self.usual, "usual"), (self.second, "second")):
            home.mkdir()
            (home / "auth.json").write_text(login(name))
        patcher = patch.dict(os.environ, {
            "HOME": str(self.home), "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
            "AGENTKIT_SESSION": "atoll", "XAI_API_KEY": API_KEY})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("GROK_HOME", "AGENTKIT_ACCOUNT", config.ADAPTER_DIR_ENV):
            os.environ.pop(name, None)
        self.env = {**os.environ}
        self.prompt = self.work / "prompt.md"
        self.prompt.write_text("Reply with the single word ok.\n")

    def adapter(self, *args, account="", env=None, stdin=subprocess.DEVNULL):
        """The adapter as ak calls it: the account's name, empty for the usual login."""
        return subprocess.run([str(ADAPTER), *map(str, args)], capture_output=True, text=True,
                              stdin=stdin, env={**self.env, "AGENTKIT_ACCOUNT": account,
                                                **(env or {})})

    def turn(self, account="", sid=None, out="out"):
        proc = self.adapter("run", "grok-4.7", "xhigh", self.work, self.prompt, self.work / out,
                            *([sid] if sid else []), account=account)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return (self.work / out / "session_id").read_text()

    def calls(self):
        """Every grok call since the last look: its arguments, home and API key."""
        path = self.fake / "grok-calls"
        try:
            return [json.loads(line) for line in path.read_text().splitlines()]
        except OSError:
            return []
        finally:
            path.unlink(missing_ok=True)

    def asked(self):
        """Every key the billing endpoint was asked with since the last look."""
        path = self.fake / "asked"
        try:
            return path.read_text().split()
        except OSError:
            return []
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def under(path, *roots):
        return any(path == root or path.startswith(root + "/") for root in roots)

    def tree(self):
        """Every path under HOME, with what it holds: bytes, a link's target, or a directory."""
        found = {}
        for root, dirs, files in os.walk(self.home):
            for name in dirs + files:
                path = Path(root, name)
                found[str(path.relative_to(self.home))] = (
                    "-> " + os.readlink(path) if path.is_symlink()
                    else path.read_bytes() if path.is_file() else "dir")
        return found

    def written(self, verb, account="", env=None, stdin=subprocess.DEVNULL):
        """That verb's answer, and every path under HOME it added, changed or removed."""
        before = self.tree()
        proc = self.adapter(*verb, account=account, env=env, stdin=stdin)
        after = self.tree()
        return proc, sorted(p for p in before.keys() | after.keys()
                            if before.get(p) != after.get(p))

    def weekly(self):
        """The captured weekly credits body, its window around now."""
        body = json.loads((FIX / "grok-billing-weekly.json").read_text())
        end = int(time.time()) + 3 * 86400
        body["config"]["currentPeriod"].update(
            {edge: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(at))
             for edge, at in (("start", end - 604800), ("end", end))})
        return json.dumps(body)

    VERBS = (("run", "grok-4.7", "xhigh", "{work}", "{prompt}", "{work}/out"), ("usage",),
             ("auth",), ("auth", "seat"), ("login",), ("hooks",), ("models",),
             ("interactive", "grok-4.7", "xhigh"))

    def verbs(self):
        return [tuple(a.format(work=self.work, prompt=self.prompt) for a in verb)
                for verb in self.VERBS]

    def test_a_named_account_uses_only_its_own_home_in_every_verb(self):
        (self.fake / f"resp-{token('second')}").write_text("200\n" + self.weekly())
        answers = {}
        for verb in self.verbs():
            with self.subTest(verb=verb):
                proc, paths = self.written(verb, account="second")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                answers[verb[0] if verb != ("auth", "seat") else "seat"] = proc.stdout
                # its own home, its own state, the shared conversations and what the verb was
                # handed -- the seat's rulebook, the turn's own directory -- and nothing else
                self.assertEqual([p for p in paths if not (
                    self.under(p, ".grok-second", ".grok/sessions", "work", "fake")
                    or p in (".agentkit/state/grok-refused-second",
                             ".agentkit/state/rulebook-atoll.md"))], [])
                for call in self.calls():
                    self.assertEqual((call["home"], call["key"]), (str(self.second), None),
                                     call)
        self.assertEqual(self.asked(), [token("second")])
        self.assertEqual(json.loads(answers["usage"])["meters"][0]["name"], "weekly")
        for verb in ("auth", "seat"):   # the account's file, never the API key beside it
            self.assertIn(f"the login in {self.second}/auth.json is saved", answers[verb])
        self.assertEqual(answers["login"].strip(), "grok: already logged in")
        # the seat carries the account's home, and finds agentkit's hooks there; the
        # conversations are the usual home's, so a seat on either resumes the other's
        words = shlex.split(answers["interactive"])
        self.assertEqual(words[:5], ["env", "-u", "XAI_API_KEY", f"GROK_HOME={self.second}",
                                     "python3"])
        hooks = json.loads((self.second / "hooks/agentkit.json").read_text())
        self.assertIn("seat-state.sh", json.dumps(hooks["hooks"]["Stop"]))
        self.assertFalse((self.usual / "hooks").exists())
        self.assertEqual((self.second / "sessions").resolve(), (self.usual / "sessions").resolve())

    def test_the_usual_login_is_today_s(self):
        (self.fake / "resp").write_text("200\n" + self.weekly())
        custom = self.home / "custom"
        custom.mkdir()
        (custom / "auth.json").write_text(login("custom"))
        for label, home, env, key in (("no GROK_HOME", self.usual, {}, "usual"),
                                      ("the user's GROK_HOME", custom,
                                       {"GROK_HOME": str(custom)}, "custom")):
            for verb in self.verbs():
                with self.subTest(label=label, verb=verb):
                    proc, paths = self.written(verb, env=env)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    ours = str(home.relative_to(self.home))
                    self.assertEqual([p for p in paths if not (
                        self.under(p, ours, "work", "fake")
                        or p == ".agentkit/state/rulebook-atoll.md")], [])
                    for call in self.calls():
                        self.assertEqual((call["home"], call["key"]),
                                         (env.get("GROK_HOME"), API_KEY), call)
                    if verb[0] == "usage":
                        self.assertEqual(self.asked(), [token(key)])
                    elif verb[0] == "auth":
                        self.assertEqual(proc.stdout.strip(), "grok: XAI_API_KEY is set")
                    elif verb[0] == "interactive":
                        self.assertEqual(shlex.split(proc.stdout)[0], "python3")
            self.assertTrue((home / "hooks/agentkit.json").is_file())
        self.assertEqual(sorted(p.name for p in self.home.glob(".grok*")), [".grok", ".grok-second"])
        self.assertFalse((self.second / "sessions").exists())

    def test_a_refusal_is_written_down_for_its_own_login(self):
        # The account's key lapsed, grok renewed it, and the endpoint refused the renewed one:
        # that logout is the account's alone, and the usual login is still one.
        (self.second / "auth.json").write_text(
            login("lapsed", expires="2020-06-01T00:00:00Z", refresh=True))
        (self.fake / "renewed-.grok-second").write_text(login("renewed", refresh=True))
        (self.fake / "resp").write_text('401\n{"error":"expired"}')
        (self.fake / f"resp-{token('usual')}").write_text("200\n{}")
        proc = self.adapter("usage", account="second")
        self.assertIn("grok login", json.loads(proc.stdout)["error"])
        self.assertEqual(self.asked(), [token("lapsed"), token("renewed")])
        self.assertEqual(sorted(p.name for p in self.state.glob("grok-*")),
                         ["grok-refused-second"])
        self.assertEqual(self.adapter("auth", account="second").returncode, 1)
        self.assertEqual(self.adapter("auth", env={"XAI_API_KEY": ""}).returncode, 0)
        # the usual login answered: its own refusal is cleared, and the account's stands
        self.adapter("usage", env={"XAI_API_KEY": ""})
        self.assertEqual(self.asked(), [token("usual")])
        self.assertTrue((self.state / "grok-refused-second").is_file())
        auth = self.adapter("auth", account="second")
        self.assertEqual(auth.returncode, 1)
        self.assertIn(f"{self.second}/auth.json after grok's own renewal", auth.stderr)

    def test_a_conversation_resumes_on_the_other_subscription(self):
        # The fake refuses to resume a conversation its home does not hold, as grok does.
        for first, then in (("", "second"), ("second", "")):
            with self.subTest(first=first or "default", then=then or "default"):
                sid = self.turn(account=first, out=f"begun-{first}")
                self.assertTrue(grokbuild.opened(self.work, sid))
                self.assertEqual(self.turn(account=then, sid=sid, out=f"resumed-{then}"), sid)
                self.assertEqual([c["home"] for c in self.calls()],
                                 [str(self.second) if a else None for a in (first, then)])

    def test_login_signs_the_account_in_to_its_own_home(self):
        (self.second / "auth.json").unlink()
        usual = (self.usual / "auth.json").read_text()
        (self.fake / "login").write_text(login("signed"))
        # the usual login is saved, but it is not this account's
        proc = self.adapter("login", account="second")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("not logged in", proc.stderr)
        master, tty = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, tty)
        proc, paths = self.written(("login",), account="second", stdin=tty)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([c["args"] for c in self.calls()], [["login"]])
        self.assertEqual((self.second / "auth.json").read_text(), login("signed"))
        self.assertEqual((self.usual / "auth.json").read_text(), usual)
        self.assertEqual([p for p in paths
                          if not self.under(p, ".grok-second", ".grok/sessions", "fake")], [])
        self.assertEqual(self.adapter("login", account="second").stdout.strip(),
                         "grok: already logged in")


if __name__ == "__main__":
    unittest.main()
