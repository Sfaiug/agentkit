"""tests/fixtures/notes.py reads its socket as notes are sent: a child sends more notes with a
blocking `sendto` than any socket holds unread (512 on a host, 10 in the landing's sandbox) while
the test only waits for it to end, and the fixture hands back every one in the order sent, then
none."""

from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.notes import Notes

SEND = """import socket
sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
for n in range(600):
    sender.sendto(str(n).encode(), {address!r})
"""


class NotesAreReadAsSent(unittest.TestCase):
    def test_600_notes_sent_unread_come_back_in_order_then_none(self):
        notes = Notes()
        subprocess.run([sys.executable, "-c", SEND.format(address=notes.address)],
                       check=True, timeout=60)
        self.assertEqual(notes.since(), [str(n) for n in range(600)])
        self.assertEqual(notes.since(), [])


if __name__ == "__main__":
    unittest.main()
