"""`ak models --json` compares and answers off a single lineup even when another refresh replaces
`state/matrix.json` between reads, never mixing one lineup's rows with another's compared releases
into an empty front.

Black-box: the program `AK_BIN` names, run from outside (tests/fixtures/akbin.py) on boards from
tests/test_key_models_answer.py, with `state/matrix.json` served through a FIFO that hands two
distinct valid lineups to consecutive reads; judged by the JSON output and exit code.  Fails
against /bin/false.
"""

import json
import os
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, NOW, boards


def showing(held, model, at):
    return {key: {**board, "asked_at": NOW, "fetched_at": at,
                  "rows": [row for row in board["rows"] if row["model"] == model]}
            for key, board in held.items()}


class ModelsJsonSingleLineup(unittest.TestCase):
    def test_concurrent_matrix_replacement_never_mixes_lineups(self):
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"}},
                       settings={"companies": ["Acme"]})
        held = boards()
        matrix_path = home.path / ".agentkit/state/matrix.json"

        def record(model, at):
            matrix_path.unlink(missing_ok=True)
            home.write(".agentkit/state/boards.json", showing(held, model, at))
            done = home.ak("models", "--json", env=ENV)
            self.assertEqual(done.code, 0, done.err)
            return matrix_path.read_bytes(), {
                row["release"] for row in json.loads(done.out)["execute"]["front"]}

        first, first_front = record("Acme Max 5", NOW - 10)
        second, second_front = record("Acme Mid 5", NOW - 5)
        self.assertEqual(first_front, {"acme-max-5"})
        self.assertEqual(second_front, {"acme-mid-5"})

        # Restore the first boards (older than `first`'s computed_at) so refresh hits the cache,
        # then feed `first` on the first read of matrix.json and `second` on any second read.
        home.write(".agentkit/state/boards.json", showing(held, "Acme Max 5", NOW - 10))
        matrix_path.unlink()
        os.mkfifo(matrix_path)
        keep = matrix_path.with_suffix(".fifo")
        os.link(matrix_path, keep)
        stop = threading.Event()

        def serve():
            for payload in (first, second):
                if stop.is_set():
                    return
                fd = os.open(matrix_path, os.O_WRONLY)
                try:
                    if stop.is_set():
                        return
                    with os.fdopen(fd, "wb", closefd=False) as out:
                        out.write(payload)
                except BrokenPipeError:
                    return
                finally:
                    os.close(fd)
            tmp = matrix_path.with_suffix(".next")
            tmp.write_bytes(second)
            tmp.replace(matrix_path)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            done = home.ak("models", "--json", env=ENV, timeout=30)
        finally:
            stop.set()
            while thread.is_alive():
                try:
                    fd = os.open(keep, os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    break
                os.close(fd)
                thread.join(0.05)
            thread.join()
            keep.unlink(missing_ok=True)
        self.assertEqual(done.code, 0, done.err)
        releases = {row["release"] for row in json.loads(done.out)["execute"]["front"]}
        self.assertIn(releases, ({"acme-max-5"}, {"acme-mid-5"}))


if __name__ == "__main__":
    unittest.main()
