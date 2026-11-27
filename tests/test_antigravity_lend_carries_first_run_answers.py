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
# not as tools/lend.py would write them: they are lent as they are, to the byte
ANSWERS = '{"consumerOnboardingComplete":true,"onboardingComplete":true}\n'


def answered(path):
    path.write_text(ANSWERS)


class AntigravityLendCarriesFirstRunAnswers(unittest.TestCase):
    def lend(self, data, give=None, account="", held={}, code=0, cap=None):
        """What a home that held `held` holds, as {path: text}, once `lend` from an owner's login
        in `data`, where `give` made the answers, able to write no file past `cap` bytes, exited
        `code`."""
        with tempfile.TemporaryDirectory() as temp:
            owner, home = Path(temp) / "owner", Path(temp) / "check"
            login = owner / ".gemini" / data
            (login / "cache").mkdir(parents=True)
            (login / "antigravity-oauth-token").write_text(TOKEN)
            if give:
                give(login / "cache/onboarding.json")
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
            placed = self.lend(data, answered, account=account)
            self.assertEqual(placed[f".gemini/{data}/cache/onboarding.json"], ANSWERS)

    def test_an_owner_who_gave_none_lends_the_login_alone(self):
        # no file where they go, or a pipe there, which a lend reading it would wait on
        for give in (None, os.mkfifo):
            placed = self.lend("antigravity-cli", give)
            self.assertEqual(list(placed), [".gemini/antigravity-cli/antigravity-oauth-token"])

    def test_a_home_with_no_place_for_the_answers_is_lent_no_login_either(self):
        # answers of its own, then a file where their folder goes: it stays as it was
        for taken in ("cache/onboarding.json", "cache"):
            held = {f".gemini/antigravity-cli/{taken}": "its own"}
            self.assertEqual(self.lend("antigravity-cli", answered, held=held, code=2), held)

    @unittest.skipIf(os.geteuid() == 0, "root reads a file whatever its mode")
    def test_answers_the_lend_cannot_read_are_not_left_out_no_login_is_lent(self):
        # closed to it: the answers, then the folder they are in.  A home's own answers stay.
        for closed in (lambda path: path, lambda path: path.parent):
            def give(path):
                answered(path)
                closed(path).chmod(0)
            for held in ({}, {".gemini/antigravity-cli/cache/onboarding.json": "its own"}):
                self.assertEqual(self.lend("antigravity-cli", give, held=held, code=2), held)

    def test_answers_cut_short_as_they_are_written_go_back_with_the_login(self):
        # no file grows past the login's size, so of the answers, longer, only a part is written
        self.assertEqual(self.lend("antigravity-cli", answered, code=2, cap=len(TOKEN)), {})


if __name__ == "__main__":
    unittest.main()
