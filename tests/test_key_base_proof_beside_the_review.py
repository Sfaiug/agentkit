"""The task's base proof runs beside its review and is recorded before delivery.

Black-box through AK_BIN, akbin, gitrig, fakeadapter and fakegh. On old code the
check waits for the reviewer to start; markers judge their order, never elapsed time.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import shlex
import sys
import threading
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

PROVEN = "base proof: a check fails on the old code and passes with this change"


def markers(folder):
    # The check's and reviewer's boxes share no writable paths; loopback carries their markers.
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.removeprefix("/")
            if name == "reviewing":
                (folder / "saw-waiting").write_text(json.dumps(
                    (folder / "waiting").exists() and not (folder / "done").exists()))
            if name != "started":
                (folder / name).touch()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"yes" if (folder / "reviewing").exists() else b"no")

        def log_message(self, *_args):
            pass
    return HTTPServer(("127.0.0.1", 0), Handler)


class BesideTheReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig, cls.gh = Rig(home, "widgets"), GitHub(home)
        cls.gh.grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        fakes = fakeadapter.install(home, claude="work", codex="pass")
        folder = fakes["codex"].dir
        cls.saw = folder / "saw-waiting"
        server = markers(folder)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        cls.addClassCleanup(server.server_close)
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        script = f"""import pathlib, sys, time, urllib.request
if pathlib.Path('retry.txt').exists():
    sys.exit(0)
def mark(name):
    return urllib.request.urlopen({url!r} + '/' + name, timeout=5).read()
mark('waiting')
deadline = time.monotonic() + 30
while mark('started') != b'yes' and time.monotonic() < deadline:
    time.sleep(0.01)
mark('done')
sys.exit(1)
"""
        fakes["claude"].behave({**fakeadapter.WORK, "write": {
            "retry.txt": "hello\n", "tests/test_retry.py": script}})
        started = f"import urllib.request; urllib.request.urlopen({url + '/reviewing'!r})"
        fakes["codex"].behave({"sh": f"python3 -c {shlex.quote(started)}",
                               "hand_in": [["done"]], "final": "Reviewed."})
        task = taskfile.write(home, rig.path, "Add retry file",
                              done_when=("python3 tests/test_retry.py",))
        cls.done = home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_reviewer_starts_while_the_base_replay_is_waiting(self):
        self.assertTrue(json.loads(self.saw.read_text()),
                        (self.run_dir / "log.txt").read_text())

    def test_the_run_merges_and_records_the_proof(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertTrue(self.state["merged"])
        self.assertEqual(self.state["base_proof"], "proven")
        self.assertIn(PROVEN, (self.run_dir / "result.md").read_text().splitlines())
        self.assertIn(f"- {PROVEN}", self.gh.pr(1)["body"].splitlines())

    def test_the_reviewer_gets_no_base_proof_line(self):
        prompt = (self.run_dir / "round-1/reviewer/prompt.md").read_text()
        self.assertFalse(any(line.startswith("base proof:") for line in prompt.splitlines()))


if __name__ == "__main__":
    unittest.main()
