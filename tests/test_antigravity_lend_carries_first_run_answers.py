"""agy's lent login comes with its owner's first-run answers: a seat on it opens on its prompt."""

import json
import os
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
TOKEN = json.dumps({"token": {"refresh_token": "fixture"}})
ANSWERS = {"consumerOnboardingComplete": True, "onboardingComplete": True}


class AntigravityLendCarriesFirstRunAnswers(unittest.TestCase):
    def lend(self, data, answered, account="", held={}, code=0, cap=None):
        """What a home that held `held` holds, as {path: text}, once `lend` from an owner's login
        in `data`, able to write no file past `cap` bytes, exited `code`."""
        with tempfile.TemporaryDirectory() as temp:
            owner, home = Path(temp) / "owner", Path(temp) / "check"
            login = owner / ".gemini" / data
            (login / "cache").mkdir(parents=True)
            (login / "antigravity-oauth-token").write_text(TOKEN)
            if answered:
                (login / "cache/onboarding.json").write_text(json.dumps(ANSWERS))
            for path, text in held.items():
                (home / path).parent.mkdir(parents=True, exist_ok=True)
                (home / path).write_text(text)
            env = {"HOME": str(owner), "PATH": os.environ["PATH"], "AGENTKIT_ACCOUNT": account}
            command = [str(REPO / "adapters/antigravity.sh"), "lend", str(home)]
            lent = subprocess.run(
                command + ["own"] * bool(account), env=env, capture_output=True, text=True,
                timeout=20, preexec_fn=cap and (
                    lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))))
            self.assertEqual(lent.returncode, code, lent.stderr)
            return {str(path.relative_to(home)): path.read_text()
                    for path in home.rglob("*") if path.is_file()}

    def test_the_answers_go_beside_the_login_lent_the_usual_or_an_accounts_own(self):
        for data, account in (("antigravity-cli", ""), ("antigravity-cli-acme", "acme")):
            placed = self.lend(data, answered=True, account=account)
            self.assertEqual(json.loads(placed[f".gemini/{data}/cache/onboarding.json"]), ANSWERS)

    def test_an_owner_who_gave_none_lends_the_login_alone(self):
        placed = self.lend("antigravity-cli", answered=False)
        self.assertEqual(list(placed), [".gemini/antigravity-cli/antigravity-oauth-token"])

    def test_a_home_with_no_place_for_the_answers_is_lent_no_login_either(self):
        # answers of its own, then a file where their folder goes: it stays as it was
        for taken in ("cache/onboarding.json", "cache"):
            held = {f".gemini/antigravity-cli/{taken}": "its own"}
            self.assertEqual(self.lend("antigravity-cli", answered=True, held=held, code=2), held)

    def test_answers_cut_short_as_they_are_written_go_back_with_the_login(self):
        # no file grows past the login's size, so of the answers, longer, only a part is written
        self.assertEqual(self.lend("antigravity-cli", answered=True, code=2, cap=len(TOKEN)), {})


if __name__ == "__main__":
    unittest.main()
