"""OpenCode runs any provider it can log in to, and answers for whichever one ak names.

ak names the providers a call is about in AGENTKIT_PROVIDER (tests/test_provider_named.py).
The adapter reads which providers are logged in off OpenCode's own list (`opencode api
provider.list`), its models and their efforts off `opencode api model.list`, and logs in to
the one named with `opencode auth login <provider>`; each named needs its own login.

Offline: a stub `opencode` on PATH answers from files the test writes, in a sandbox HOME.  The
model list is tests/fixtures/opencode-model-list.json, OpenCode 2.0.24's own with every
provider's settings taken out.  `acme` and `zeta` are invented providers.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import REPO, Sandbox  # noqa: E402
from agentkit import config  # noqa: E402

ADAPTER = str(REPO / "adapters/opencode.sh")
FIXTURES = REPO / "tests/fixtures"

# `api <operation>` cats $STUB_DIR/<operation>.json, failing where there is none; every argv
# lands in $STUB_DIR/argv.log.
STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$STUB_DIR/argv.log"
case "$1" in
  api) [ -f "$STUB_DIR/$2.json" ] || exit 1; cat -- "$STUB_DIR/$2.json" ;;
  --version) echo "opencode v9.9.9-test" ;;
  *) echo "stub opencode: $*" >&2; exit 2 ;;
esac
"""


class AnyProvider(Sandbox):
    def setUp(self):
        super().setUp()
        self.stub = self.root / "stub"
        self.stub.mkdir()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "opencode").write_text(STUB)
        (bin_dir / "opencode").chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{bin_dir}:/usr/bin:/bin", "STUB_DIR": str(self.stub)}))
        for name in (config.ACCOUNT_ENV, config.PROVIDER_ENV, config.ADAPTER_DIR_ENV,
                     "OPENCODE_CONFIG", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            os.environ.pop(name, None)
        self.logged_in("acme")

    def logged_in(self, *providers):
        """OpenCode's own list: its free provider, and these, enabled."""
        listed = [{"id": name, "name": name.title(), "activation": "enabled",
                   "settings": {"apiKey": "dummy"}} for name in ("opencode", *providers)]
        (self.stub / "provider.list.json").write_text(json.dumps({"data": listed}))

    def adapter(self, *args, provider=None):
        env = dict(os.environ)
        if provider is not None:
            env[config.PROVIDER_ENV] = provider
        return subprocess.run([ADAPTER, *args], capture_output=True, text=True, env=env,
                              stdin=subprocess.DEVNULL, timeout=60)

    def asked(self):
        try:
            return (self.stub / "argv.log").read_text().splitlines()
        except OSError:
            return []

    def test_each_provider_named_answers_with_its_own_login(self):
        proc = self.adapter("auth", provider="acme")
        self.assertEqual((proc.returncode, proc.stdout.strip()),
                         (0, "opencode: OpenCode lists acme as logged in"), proc.stderr)
        proc = self.adapter("auth", provider="zeta")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stderr.strip(),
                         "opencode: no login for zeta; run `opencode auth login zeta`")
        # several named: each needs its own
        self.assertEqual(self.adapter("auth", provider="acme zeta").returncode, 1)
        self.logged_in("acme", "zeta")
        self.assertEqual(self.adapter("auth", provider="acme zeta").returncode, 0)
        # a key in OpenCode's own config is that provider's login, and no other's
        config_dir = Path(os.environ["OPENCODE_CONFIG_DIR"])
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "opencode.json").write_text(json.dumps(
            {"provider": {"nova": {"options": {"apiKey": "dummy"}}}}))
        proc = self.adapter("auth", provider="nova")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("a key for nova is configured", proc.stdout)
        self.assertEqual(self.adapter("auth", provider="vega").returncode, 1)

    def test_login_logs_in_to_the_provider_named(self):
        proc = self.adapter("login", provider="acme")
        self.assertEqual((proc.returncode, proc.stdout.strip()),
                         (0, "opencode: already logged in to acme"))
        proc = self.adapter("login", provider="zeta")     # no terminal to log in from
        self.assertEqual(proc.returncode, 1)
        self.assertIn("`opencode auth login zeta`", proc.stderr)

    def test_a_logged_in_provider_is_metered_none_and_one_logged_out_fails(self):
        out = json.loads(self.adapter("usage", provider="acme").stdout)
        self.assertEqual((out["provider"], out["meters"], out["error"]), ("acme", [], None))
        self.assertIn("no meter", out["none"])
        out = json.loads(self.adapter("usage", provider="zeta").stdout)
        self.assertEqual((out["provider"], out["meters"]), ("zeta", []))
        self.assertIn("no login for zeta", out["error"])
        self.assertNotIn("none", out)

    def test_models_carry_opencode_s_own_names_and_variants(self):
        (self.stub / "model.list.json").write_text(
            (FIXTURES / "opencode-model-list.json").read_text())
        proc = self.adapter("models")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = {line.split("\t")[0]: line.split("\t")[1:] for line in proc.stdout.splitlines()}
        self.assertEqual(rows["opencode/glm-5.3-flash-free"], ["GLM-5.3-Flash Free", "low high max"])
        # no variant is a model that runs at no effort, which `run` hands bare
        self.assertEqual(rows["opencode/big-pickle"], ["Big Pickle", "none"])
        # so a variant OpenCode names `none` is not offered: ak's `none` would hand it bare
        self.assertEqual(rows["opencode/nemotron-3.5-super-vl-free"],
                         ["Nemotron 3.5 Super VL Free", "minimal low medium high xhigh"])
        # MiMo's own come from the table, whose thinking switch reaches its API
        self.assertEqual(rows["mimo/mimo-v2.6-pro"], ["MiMo V2.6 Pro", "none high"])
        self.assertNotIn("--standalone", " ".join(self.asked()))


if __name__ == "__main__":
    unittest.main()
