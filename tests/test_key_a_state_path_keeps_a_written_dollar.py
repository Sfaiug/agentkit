"""A harness's state path keeps a dollar its manifest writes as `$$`, a `${NAME:-default}` after it
included: an `ak worker` turn writes in that folder, named as written, and the host keeps what it
wrote.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
with a config from akconfig.py and a scripted harness from fakeadapter.py, whose `sh` step
writes from inside the turn.
"""

import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home, boxable


@unittest.skipUnless(boxable(), "no bwrap able to box a turn here")
class AStatePathKeepsAWrittenDollar(unittest.TestCase):
    def test_a_turn_writes_in_the_folder_named_as_written(self):
        with Home() as home:
            akconfig.write(home, {"beta": {"harness": "acme", "model": "beta-1",
                                           "effort": "low"}})
            fake = fakeadapter.install(home, acme="pass")["acme"]
            text = fake.manifest.read_text()
            fake.manifest.write_text(text.replace(
                "state = [", 'state = ["~/.acme/$${ACME_STATE:-fallback}", ', 1))
            made = home.path / ".acme" / "${ACME_STATE:-fallback}" / "made.txt"
            fake.behave({**fakeadapter.PASS, "sh": f"echo turn > {shlex.quote(str(made))}"})
            ws = home.path / "code" / "widgets"
            ws.mkdir(parents=True)
            task = home.write("fix-api.md", "Fix the api.\n")
            done = home.ak("worker", "beta", str(task), "--workspace", str(ws),
                           "--out", str(home.path / "out"))
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(made.read_text(), "turn\n")


if __name__ == "__main__":
    unittest.main()
