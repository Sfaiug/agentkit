"""A harness's state path takes a variable's value as written, a dollar in it included, when the
manifest names it `${NAME:-default}`: an `ak worker` turn writes in that folder and the host keeps
what it wrote.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, with a config from akconfig.py and a scripted harness from
fakeadapter.py, whose `sh` step writes from inside the turn.
"""

import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home, boxable


@unittest.skipUnless(boxable(), "no bwrap able to box a turn here")
class AStatePathTakesAValueAsWritten(unittest.TestCase):
    def test_a_turn_writes_in_the_folder_the_variable_names(self):
        with Home() as home:
            akconfig.write(home, {"beta": {"harness": "acme", "model": "beta-1",
                                           "effort": "low"}})
            fake = fakeadapter.install(home, acme="pass")["acme"]
            text = fake.manifest.read_text()
            fake.manifest.write_text(text.replace(
                "state = [", 'state = ["${ACME_STATE:-~/.acme-unused}", ', 1))
            state = home.path / "data" / "$project"
            made = state / "made.txt"
            fake.behave({**fakeadapter.PASS, "sh": f"echo turn > {shlex.quote(str(made))}"})
            ws = home.path / "code" / "widgets"
            ws.mkdir(parents=True)
            task = home.write("fix-api.md", "Fix the api.\n")
            home.ak("worker", "beta", str(task), "--workspace", str(ws),
                    "--out", str(home.path / "out"), env={"ACME_STATE": str(state)})
            self.assertEqual(made.read_text(), "turn\n")


if __name__ == "__main__":
    unittest.main()
