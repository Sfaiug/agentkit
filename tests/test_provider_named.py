"""ak names the providers a login or meter question is about, so one harness can run several.

A harness may run several providers' models, each logged in apart (OpenCode runs any provider
it can log in to).  Every `usage`, `auth` and `login` call names its providers in
AGENTKIT_PROVIDER: the model's own for a turn, the provider's for its meter, and every provider
the config runs on that harness for a question about the harness as a whole -- a seat's login,
a run parked on one -- so one provider's login never answers for another's.  Readiness is kept
per provider on such a harness, so a pick withholds only the logged-out provider's models.

Offline: `relay`, an adapter written here, is logged in to the providers $LOGGED_IN lists and
records what each call was told.  `acme` and `zeta` are invented providers.
"""

import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import REPO, Sandbox  # noqa: E402
from agentkit import config, menu, usage, worker  # noqa: E402

RELAY = """#!/usr/bin/env bash
printf '%s %s\\n' "$1" "${AGENTKIT_PROVIDER-unset}" >>"$ASKED"
case $1 in
  auth|login)
    for p in $AGENTKIT_PROVIDER; do
      case " $LOGGED_IN " in *" $p "*) ;; *) echo "relay: no login for $p" >&2; exit 1 ;; esac
    done
    echo "relay: logged in" ;;
  usage) printf '{"provider":"%s","meters":[],"error":null,"none":"no meter"}\\n' \\
           "$AGENTKIT_PROVIDER" ;;
  *) exit 2 ;;
esac
"""

CONFIG = """
[defaults]
orchestrator = "rocket"
workers = ["rocket", "comet"]

[models.rocket]
harness = "relay"
model = "acme/rocket-1"
effort = "high"
provider = "acme"

[models.comet]
harness = "relay"
model = "zeta/comet-2"
effort = "high"
provider = "zeta"

[providers.acme]
mode = "subscription"

[providers.zeta]
mode = "payg"
"""


class Keyboard:
    def give(self):
        pass

    def take(self):
        pass


class ProviderNamed(Sandbox):
    def setUp(self):
        super().setUp()
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "relay.sh").write_text(RELAY)
        (adapters / "relay.sh").chmod(0o755)
        shutil.copy(REPO / "tests/fixtures/adapters/echo.toml", adapters / "relay.toml")
        self.log = self.root / "asked"
        self.stack.enter_context(patch.dict(os.environ, {
            config.ADAPTER_DIR_ENV: str(adapters), "ASKED": str(self.log),
            "LOGGED_IN": "acme"}))
        for name in (config.ACCOUNT_ENV, config.PROVIDER_ENV):
            os.environ.pop(name, None)
        config.HOME.mkdir(parents=True, exist_ok=True)
        (config.HOME / "config.toml").write_text(CONFIG)
        self.cfg = config.load()

    def asked(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_a_turn_s_login_is_its_own_provider_s(self):
        self.assertIs(worker.auth_ok("relay", provider="acme")[0], True)
        self.assertIs(worker.auth_ok("relay", provider="zeta")[0], False)
        self.assertEqual(self.asked(), ["auth acme", "auth zeta"])

    def test_the_harness_as_a_whole_needs_every_provider_s_login(self):
        # a run parked on zeta's login waits for zeta's, whatever acme's says
        self.assertIs(worker.auth_ok("relay")[0], False)
        self.assertEqual(self.asked(), ["auth acme zeta"])
        os.environ["LOGGED_IN"] = "acme zeta"
        self.assertIs(worker.auth_ok("relay")[0], True)

    def test_a_pick_withholds_only_the_logged_out_provider_s_models(self):
        read = usage.readiness(self.cfg, usage.Readings({}))
        self.assertIsNone(usage.unready(self.cfg, "rocket", read))
        self.assertEqual(usage.unready(self.cfg, "comet", read), "relay is not logged in")

    def test_each_meter_is_asked_for_its_own_provider(self):
        for provider in ("acme", "zeta"):
            self.assertEqual(usage._probe(self.cfg, provider, 10000)["provider"], provider)
        self.assertEqual([line for line in self.asked() if line.startswith("usage")],
                         ["usage acme", "usage zeta"])

    def test_a_login_from_c_names_the_provider_it_is_for(self):
        with patch.object(menu, "pause"):
            failed = menu._adapter_verbs(Keyboard(), "relay", ("login",), "Zeta", provider="zeta")
        self.assertIn("relay login did not finish", failed)
        self.assertEqual(self.asked(), ["login zeta"])

    def test_c_offers_under_a_provider_only_its_own_models(self):
        catalog = [{"id": "acme/rocket-1", "label": "Rocket 1", "efforts": ["high"]},
                   {"id": "zeta/comet-2", "label": "Comet 2", "efforts": ["high"]},
                   {"id": "plain", "label": "Plain", "efforts": ["high"]}]
        with patch.object(config, "catalog", return_value=catalog):
            self.assertEqual([model["id"] for model in menu._offered(
                "relay", "test", provider="zeta")], ["zeta/comet-2", "plain"])
            self.assertEqual(len(menu._offered("relay", "test")), 3)


if __name__ == "__main__":
    unittest.main()
