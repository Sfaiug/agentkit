"""`adapters/<harness>.sh lend <home>` lends a key no renewal retires as it is.

Muse's login, Antigravity's and OpenCode's are keys that stay valid after use, so each copy is
the login itself, where a turn run with HOME=<home> reads it, 0600, and says no expiry: OpenCode's
is its config with each key it saved itself in it.  The real adapters run on a temporary HOME
holding fixture logins of fake values, with a fake of every harness program recording any call
but OpenCode's reads: `auth export` answers fixture keys, `config.get` the documents it merges
and its catalog one provider needing no login.  The harnesses whose renewal retires the login are tests/test_lend_login.py's.
"""

import itertools
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import tomllib
import unittest

import test_lend_login

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = {path.stem: tomllib.loads(path.read_text())
             for path in sorted((REPO / "adapters").glob("*.toml"))}

# Each harness's login as it keeps it: the file under HOME, the one an account `second` keeps
# (None where the adapter refuses accounts), and its contents around a key.
LOGINS = {
    "muse": dict(
        usual=".config/muse/auth.json", second=".muse-second/muse/auth.json",
        login=lambda key: {"providers": {"meta": {"api_key": key,
                                                  "user_email": "owner@acme.test"}}}),
    "antigravity": dict(
        usual=".gemini/antigravity-cli/antigravity-oauth-token",
        second=".gemini/antigravity-cli-second/antigravity-oauth-token",
        login=lambda key: {"token": {"access_token": "fixture-access", "token_type": "Bearer",
                                     "refresh_token": key, "expiry": "2026-10-28T17:36:12Z"},
                           "auth_method": "consumer", "id_token_email": "owner@acme.test"}),
    "opencode": dict(
        usual=".config/opencode/opencode.json", second=None,
        login=lambda key: {"$schema": "https://opencode.ai/config.json",
                           "provider": {"mimo": {"options": {"apiKey": key}}}}),
}

# OpenCode's reads, each answered: a saved login of its own, the config documents it merges
# (none unless a test lists them), and its catalog, where the `opencode` provider runs with no
# login and no config document names any
READS = """case "$*" in
  "auth export --standalone") exec cat "{saved}" ;;
  "api integration.list") echo '{{"data": []}}'; exit 0 ;;
  "api provider.list") echo '{{"data": [{{"id": "opencode", "activation": "enabled"}}]}}'; exit 0 ;;
  "api config.get"|"api --standalone config.get") exec cat "{docs}" ;;
esac
"""


def saved(integration, key, active=True, kind="key"):
    """A login OpenCode saved itself, as `auth export` lists it."""
    value = {"type": "key", "key": key} if kind == "key" else {
        "type": "oauth", "methodID": "browser", "refresh": key, "access": key, "expires": 0}
    return {"id": f"cred_{integration}_{key}", "integrationID": integration, "label": "default",
            "active": active, "value": value}


class LendKey(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.homes = itertools.count()
        fakes = self.root / "bin"
        fakes.mkdir()
        self.saved, self.ran = self.root / "saved.json", self.root / "ran"
        self.saved.write_text("[]")
        self.docs = self.root / "docs.json"
        self.docs.write_text("[]")
        for name, data in MANIFESTS.items():
            program = fakes / data["update"]["version"][0]
            reads = READS.format(saved=self.saved, docs=self.docs) if name == "opencode" else ""
            program.write_text(f'#!/bin/sh\n{reads}echo "$0 $*" >>"{self.ran}"\nexit 97\n')
            program.chmod(0o755)
        self.path = f"{fakes}{os.pathsep}{os.environ['PATH']}"

    def fixture(self, harness, key="fixture-key", which="usual", login=None):
        login = LOGINS[harness]["login"](key) if login is None else login
        path = self.home / LOGINS[harness][which]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(login, indent=2))
        return path, login

    def lend(self, harness, account="", home=None, provider=""):
        """Lend into `home`, by default a fresh one that does not exist yet."""
        home = home or self.root / f"lent-{next(self.homes)}"
        env = {"HOME": str(self.home), "PATH": self.path, "AGENTKIT_ACCOUNT": account,
               "AGENTKIT_PROVIDER": provider}
        proc = subprocess.run(["bash", str(REPO / f"adapters/{harness}.sh"), "lend", str(home)],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertFalse(self.ran.exists(), f"{harness} ran a harness program to lend")
        return proc, home

    def assert_lent(self, harness, proc, home, login):
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))
        dest = home / LOGINS[harness]["usual"]
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)
        self.assertEqual(json.loads(dest.read_text()), login)

    def assert_none(self, proc, home):
        """No login to lend: exit 1, one line saying so, and nothing written."""
        self.assertEqual((proc.returncode, proc.stdout), (1, ""))
        self.assertEqual(len(proc.stderr.splitlines()), 1, proc.stderr)
        self.assertFalse(home.exists())

    def test_every_adapter_with_logins_lends(self):
        listed = {name for name, data in MANIFESTS.items() if data.get("worker", {}).get("logins")}
        self.assertEqual(listed, set(LOGINS) | set(test_lend_login.LOGINS))

    def test_the_login_is_lent_as_it_is(self):
        for harness in LOGINS:
            with self.subTest(harness=harness):
                original, login = self.fixture(harness)
                before = original.read_bytes()
                proc, home = self.lend(harness)
                self.assert_lent(harness, proc, home, login)
                self.assertEqual(original.read_bytes(), before)

    def test_a_named_account_lends_its_own_login(self):
        for harness, spec in LOGINS.items():
            with self.subTest(harness=harness):
                self.fixture(harness, "fixture-usual")
                if spec["second"] is None:
                    # OpenCode keeps one login for every account, so it lends none of an account
                    self.assert_none(*self.lend(harness, "second"))
                    continue
                original, login = self.fixture(harness, "fixture-second", "second")
                before = original.read_bytes()
                proc, home = self.lend(harness, "second")
                self.assert_lent(harness, proc, home, login)
                self.assertEqual(original.read_bytes(), before)

    def test_no_login_and_a_blank_key_are_none_to_lend(self):
        for harness in LOGINS:
            with self.subTest(harness=harness):
                self.assert_none(*self.lend(harness))
                for key in ("", " \t\n"):
                    self.fixture(harness, key=key)
                    self.assert_none(*self.lend(harness))

    def test_this_home_and_a_taken_place_are_refused(self):
        for harness, spec in LOGINS.items():
            original, _ = self.fixture(harness)
            before = original.read_bytes(), original.stat().st_ino
            taken = self.root / f"taken-{harness}"
            (taken / spec["usual"]).parent.mkdir(parents=True)
            (taken / spec["usual"]).write_text("{}")
            for home in (self.home, taken):
                with self.subTest(harness=harness, home=home.name):
                    proc, _ = self.lend(harness, home=home)
                    self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr)
                    self.assertEqual((original.read_bytes(), original.stat().st_ino), before)
            self.assertEqual((taken / spec["usual"]).read_text(), "{}")

    def test_opencode_needs_a_key_for_each_provider_named(self):
        # acme has none but a blank one saved; nova's is in a legacy entry OpenCode drops for
        # the native one naming nova
        login = LOGINS["opencode"]["login"]("fixture-key")
        login["provider"]["nova"] = {"options": {"apiKey": "fixture-dropped"}}
        login["providers"] = {"nova": {"settings": {"baseURL": "https://nova.test"}}}
        self.fixture("opencode", login=login)
        self.saved.write_text(json.dumps([saved("acme", " \t")]))
        for provider in ("acme", "nova"):
            with self.subTest(provider=provider):
                self.assert_none(*self.lend("opencode", provider=f"mimo {provider}"))

    def test_opencode_lends_the_keys_it_saved_where_the_config_sets_none(self):
        # acme's blank, zen's missing and nova's missing from the native entry OpenCode reads
        # over its legacy one take the active key OpenCode saved; mimo keeps its own, and an
        # OAuth login holds no key
        login = LOGINS["opencode"]["login"]("fixture-key")
        login["provider"]["acme"] = {"options": {"apiKey": " \t", "baseURL": "https://acme.test"}}
        login["provider"]["nova"] = {"options": {"apiKey": ""}}
        login["providers"] = {"nova": {"settings": {"baseURL": "https://nova.test"}}}
        self.fixture("opencode", login=login)
        self.saved.write_text(json.dumps([
            saved("acme", "fixture-spare", active=False), saved("acme", "fixture-acme"),
            saved("zen", "fixture-zen"), saved("nova", "fixture-nova"),
            saved("mimo", "fixture-saved-mimo"), saved("oauthco", "fixture-oauth", kind="oauth")]))
        proc, home = self.lend("opencode", provider="acme zen nova mimo")
        login["provider"]["acme"]["options"]["apiKey"] = "fixture-acme"
        login["provider"]["zen"] = {"options": {"apiKey": "fixture-zen"}}
        login["providers"]["nova"]["settings"]["apiKey"] = "fixture-nova"
        self.assert_lent("opencode", proc, home, login)

    def test_opencode_lends_a_provider_that_needs_no_login(self):
        _, login = self.fixture("opencode", login={"$schema": "https://opencode.ai/config.json"})
        self.assert_lent("opencode", *self.lend("opencode", provider="opencode"), login)

    def test_opencode_lends_none_where_another_document_it_merges_names_a_provider(self):
        # Its config, listed by another spelling of its path, and a document naming no provider
        # leave the login lent; a document OpenCode merges over it naming one, in its native
        # entry or its legacy one, could log in as another, whether its path is the config's
        # and a newline or it has none (a remote one), as could any reply but one list
        path, login = self.fixture("opencode")
        doc = lambda where, info: {"type": "document", "path": str(where), "info": info}
        merged = [doc(str(path).replace("/.config/", "//.config/"), {"providers": {"mimo": {}}}),
                  {"type": "directory", "path": str(path.parent), "info": None},
                  doc(self.root / "update.jsonc", {"update": "disable"})]
        self.docs.write_text(json.dumps(merged))
        self.assert_lent("opencode", *self.lend("opencode"), login)
        other = {"provider": {"mimo": {"options": {"apiKey": "fixture-other"}}}}
        for extra in (doc(self.root / "custom.jsonc",
                          {"providers": {"acme": {"settings": {"baseURL": "https://acme.test"}}}}),
                      doc(self.root / "custom.jsonc", other), doc(f"{path}\n", other),
                      {"type": "document", "info": other}):
            with self.subTest(extra=extra):
                self.docs.write_text(json.dumps([*merged, extra]))
                self.assert_none(*self.lend("opencode"))
        for reply in ("", "{}"):
            with self.subTest(reply=reply):
                self.docs.write_text(reply)
                self.assert_none(*self.lend("opencode"))
        self.docs.unlink()
        self.assert_none(*self.lend("opencode"))


if __name__ == "__main__":
    unittest.main()
