"""agy's lent login comes with its owner's first-run answers: a seat on it opens on its prompt."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
ANSWERS = {"consumerOnboardingComplete": True, "onboardingComplete": True}


class AntigravityLendCarriesFirstRunAnswers(unittest.TestCase):
    def lend(self, data, answered, account=""):
        """What `lend` placed in a new home, as {path: text}, from an owner's login in `data`."""
        with tempfile.TemporaryDirectory() as temp:
            owner, home = Path(temp) / "owner", Path(temp) / "check"
            login = owner / ".gemini" / data
            (login / "cache").mkdir(parents=True)
            (login / "antigravity-oauth-token").write_text(
                json.dumps({"token": {"refresh_token": "fixture"}}))
            if answered:
                (login / "cache/onboarding.json").write_text(json.dumps(ANSWERS))
            env = {"HOME": str(owner), "PATH": "/usr/bin:/bin", "AGENTKIT_ACCOUNT": account}
            command = [str(REPO / "adapters/antigravity.sh"), "lend", str(home)]
            lent = subprocess.run(command + ["own"] * bool(account), env=env,
                                  capture_output=True, text=True, timeout=20)
            self.assertEqual(lent.returncode, 0, lent.stderr)
            return {str(path.relative_to(home)): path.read_text()
                    for path in home.rglob("*") if path.is_file()}

    def test_the_answers_go_beside_the_login_lent_the_usual_or_an_accounts_own(self):
        for data, account in (("antigravity-cli", ""), ("antigravity-cli-acme", "acme")):
            placed = self.lend(data, answered=True, account=account)
            self.assertEqual(json.loads(placed[f".gemini/{data}/cache/onboarding.json"]), ANSWERS)

    def test_an_owner_who_gave_none_lends_the_login_alone(self):
        placed = self.lend("antigravity-cli", answered=False)
        self.assertEqual(list(placed), [".gemini/antigravity-cli/antigravity-oauth-token"])


if __name__ == "__main__":
    unittest.main()
