"""`ak fetch --serve` hands the Mac each pending request as a line, and only one connection does.

The Mac's bridge keeps `ssh server "ak fetch --serve"` open, writes `heartbeat` lines into it
and reads back `<id>\\t<path>` for each file a fetch on this host asked for.  That line protocol
is the contract with the bridge already installed on the owner's Mac.  A request is handed off
only once its whole line is out, and a second connection (a reconnect while sshd keeps the old
one open) leaves the queue to the first, or a file would go twice.  A connection that stops
beating ends by itself, so a Mac that slept never holds the queue.  These tests run the Mac's
end of that ssh command in the test's Home.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home

# The Mac's end of the connection: it starts `ak fetch --serve`, takes each step (`read` a line,
# run a `second` connection beside it, `hold` the connection open, silent, until ak ends it, or
# send the step's text) and then hangs up.
MAC = r"""
import json, subprocess, sys
ak, steps = sys.argv[1], sys.argv[2:]
serve = subprocess.Popen([ak, "fetch", "--serve"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
seen = {"lines": []}
for step in steps:
    if step == "read":
        seen["lines"].append(serve.stdout.readline())
    elif step == "second":
        other = subprocess.run([ak, "fetch", "--serve"], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True)
        seen["second"] = [other.returncode, other.stdout, other.stderr]
    elif step == "hold":
        serve.wait()
    else:
        serve.stdin.write(step)
        serve.stdin.flush()
out, err = serve.communicate()
seen.update(code=serve.returncode, out=out, err=err)
print(json.dumps(seen))
"""
REQUESTS = ".agentkit/macbridge/requests"
ASKED = {"path": "/Users/acme/x.pdf", "basename": "x.pdf"}
LINE = "0123456789abcdef\t/Users/acme/x.pdf\n"


class Serve(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.requests = self.home.path / REQUESTS

    def connect(self, *steps):
        """What `ak fetch --serve` printed to the Mac given those steps, and how it ended."""
        done = self.home.run(sys.executable, "-c", MAC, AK, *steps, timeout=90)
        self.assertEqual(done.code, 0, done.err)
        return json.loads(done.out)

    def ask(self, ident, request=ASKED):
        self.home.write(f"{REQUESTS}/{ident}", request)

    def left(self):
        return sorted(path.name for path in self.requests.iterdir())

    def test_a_pending_request_is_relayed_as_its_id_and_path_once_the_mac_beats(self):
        self.ask("0123456789abcdef")
        self.ask("bad-name", {})
        seen = self.connect("heartbeat\n", "read")
        self.assertEqual(seen["lines"], [LINE])
        self.assertEqual((seen["code"], seen["out"], seen["err"]), (0, "", ""))
        # Handed off: the next connection must not send it again.
        self.assertEqual(self.left(), ["bad-name"])

    def test_nothing_is_relayed_to_a_connection_that_never_sent_a_whole_heartbeat(self):
        self.ask("0123456789abcdef")
        for said in ("hello\n", "heartbeat"):
            with self.subTest(said=said):
                seen = self.connect(said)
                self.assertEqual((seen["lines"], seen["code"], seen["out"], seen["err"]),
                                 ([], 0, "", ""))
                self.assertEqual(self.left(), ["0123456789abcdef"])

    def test_a_request_it_cannot_send_is_dropped_and_named_and_the_rest_still_go(self):
        self.ask("0000000000000000", {"basename": "x.pdf"})
        self.ask("0000000000000001", {"path": "/Users/acme/a\tb.pdf", "basename": "a_b.pdf"})
        self.ask("0123456789abcdef")
        seen = self.connect("heartbeat\n", "read")
        self.assertEqual((seen["lines"], seen["code"], seen["out"]), ([LINE], 0, ""))
        for ident in ("0000000000000000", "0000000000000001"):
            self.assertIn(ident, seen["err"])
        self.assertEqual(self.left(), [])

    def test_a_second_connection_leaves_the_queue_to_the_first_until_it_hangs_up(self):
        self.ask("0123456789abcdef")
        seen = self.connect("heartbeat\n", "read", "second")
        self.assertEqual(seen["lines"], [LINE])
        self.assertEqual(seen["second"],
                         [0, "", "ak fetch --serve: another connection holds serve.lock; "
                                 "exiting\n"])
        self.assertEqual((seen["code"], seen["out"], seen["err"]), (0, "", ""))
        self.ask("fedcba9876543210", {"path": "/Users/acme/y.pdf", "basename": "y.pdf"})
        seen = self.connect("heartbeat\n", "read")
        self.assertEqual(seen["lines"], ["fedcba9876543210\t/Users/acme/y.pdf\n"])

    def test_a_connection_that_stops_beating_ends_by_itself(self):
        # sshd may keep a sleeping Mac's connection open, and the queue must not stay held.
        self.ask("0123456789abcdef")
        seen = self.connect("heartbeat\n", "read", "hold")
        self.assertEqual(seen["lines"], [LINE])
        self.assertEqual((seen["code"], seen["out"], seen["err"]), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
