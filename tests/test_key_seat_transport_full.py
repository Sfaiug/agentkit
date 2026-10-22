"""A seat's terminal carries a full screen out while a full draft waits to go in, every byte.

The owner rule: terminal input and output keep moving when both fill at once, for every model
and harness, in the shared transport.  The transport is whatever a seat's launch line puts
before the harness, so this takes that line from `ak orch NAME --model opus --dry-run` as the
program `AK_BIN` names prints it, and runs it with a harness of the test's own in the harness's
place.  The harness draws a mebibyte without reading while about a mebibyte of mouse moves and
a draft are already waiting for it, then reads what was typed and exits 7.  A transport that
blocks on either side never finishes; one that drops, adds or reorders a byte, or keeps the
harness's exit status from the pane, is caught by what arrives.
"""

import hashlib
import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

# On the terminal the transport gives it: raw, as a harness takes it, before saying it is
# ready, so nothing typed is echoed or held for a line.
HARNESS = r'''
import hashlib, os, sys, time, tty
root, size = sys.argv[1], int(sys.argv[2])
tty.setraw(0)
open(os.path.join(root, "ready"), "w").close()
while not os.path.exists(os.path.join(root, "go")):
    time.sleep(0.01)
view = memoryview(bytes(range(256)) * 4096)
while view:
    view = view[os.write(1, view):]
got = bytearray()
while len(got) < size:
    got += os.read(0, 65536)
with open(os.path.join(root, "received"), "w") as out:
    out.write(hashlib.sha256(got[:size]).hexdigest())
sys.exit(7)
'''

# The owner's side: everything typed is queued before the harness starts drawing, and the
# screen is read while the rest still goes in.
OWNER = r'''
import hashlib, json, os, select, subprocess, sys, time
root = sys.argv[1]
typed = b"\x1b[<35;12;6M" * 95325 + b"an owner draft\x1b"
seat = subprocess.Popen([*sys.argv[2:], sys.executable, os.path.join(root, "harness.py"), root,
                         str(len(typed))], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
while not os.path.exists(os.path.join(root, "ready")) and seat.poll() is None:
    time.sleep(0.01)
for stream in (seat.stdin, seat.stdout):
    os.set_blocking(stream.fileno(), False)
pending = memoryview(typed)
def push():
    global pending
    while pending:
        try:
            pending = pending[os.write(seat.stdin.fileno(), pending):]
        except BlockingIOError:
            return
push()
open(os.path.join(root, "go"), "w").close()
shown = bytearray()
while True:
    readable, writable, _ = select.select([seat.stdout], [seat.stdin] if pending else [], [])
    if readable:
        chunk = os.read(seat.stdout.fileno(), 65536)
        if not chunk:
            break
        shown += chunk
    if writable:
        push()
print(json.dumps({"code": seat.wait(), "unsent": len(pending),
                  "shown": hashlib.sha256(shown).hexdigest(), "size": len(shown),
                  "typed": hashlib.sha256(typed).hexdigest()}))
'''


class SeatTransport(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def transport(self):
        """The seat's launch line up to its harness, `claude` for opus."""
        checkout = self.home.path / "code" / "acme"
        checkout.mkdir(parents=True)
        done = self.home.ak("orch", "acme", "--model", "opus", "--dry-run", cwd=checkout)
        self.assertEqual(done.code, 0, done.err)
        words = shlex.split(done.out.strip().splitlines()[-1])
        at = next((i for i, word in enumerate(words) if Path(word).name == "claude"), None)
        self.assertIsNotNone(at, done.out)
        # `env` first: a launch line may begin with a variable it sets
        return ["env", *words[:at]]

    def test_a_full_screen_out_and_a_full_draft_in_both_arrive_whole(self):
        root = self.home.root / "transport"
        root.mkdir()
        (root / "harness.py").write_text(HARNESS)
        (root / "owner.py").write_text(OWNER)
        # a transport that blocks either side hangs here, and the bound ends it
        done = self.home.run(sys.executable, str(root / "owner.py"), str(root),
                             *self.transport(), timeout=90)
        self.assertEqual(done.code, 0, done.err)
        moved = json.loads(done.out)
        self.assertEqual(moved["code"], 7, done.err)
        self.assertEqual(moved["unsent"], 0)
        self.assertEqual(moved["size"], 256 * 4096)
        self.assertEqual(moved["shown"], hashlib.sha256(bytes(range(256)) * 4096).hexdigest())
        self.assertEqual((root / "received").read_text(), moved["typed"])


if __name__ == "__main__":
    unittest.main()
