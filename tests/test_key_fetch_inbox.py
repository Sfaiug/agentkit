"""`ak fetch PATH` asks the Mac for a file this host lacks and prints the copy the Mac delivers.

The owner drags a file from the Mac into a session, and the agent runs `ak fetch` on the path it
sees so it can read the file here.  The Mac's bridge answers through files under
`~/.agentkit/macbridge`: a request in `requests/` names the path, and the answer lands in
`inbox/` as the file itself, an error the Mac hit, or a mark saying the file is gone.  That
exchange is the contract with the bridge already installed on the owner's Mac, so these tests
play the Mac's side from outside and hold for whichever build `AK_BIN` names.  A fetch nobody
answers has to give up, and no answer may leave a request or a mark behind.
"""

import json
from pathlib import Path
import re
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

REQUEST = re.compile(r"[0-9a-f]{16}")
REPORT = "/Users/acme/Desktop/report.pdf"
GONE = "/Users/acme/x.pdf"
NO_ANSWER = (f"ak fetch: {GONE}: no answer from the Mac bridge in 0s; the Mac may be asleep or "
             "offline, or ak macbridge is not running there (open ak on the Mac)\n")
USAGE = "ak fetch: usage: ak fetch PATH [PATH ...] | ak fetch --serve\n"


class Mac(threading.Thread):
    """The bridge on the Mac: it reads the first request ak leaves and answers it with
    `answer(inbox, ident)` once the file has come over."""

    def __init__(self, home, answer):
        super().__init__(daemon=True)
        self.bridge = home.path / ".agentkit/macbridge"
        self.answer, self.asked, self.request = answer, None, None
        self.stop = threading.Event()

    def run(self):
        requests = self.bridge / "requests"
        while not self.stop.wait(0.02):
            for request in requests.iterdir() if requests.is_dir() else ():
                if REQUEST.fullmatch(request.name):
                    self.request, self.asked = request.name, json.loads(request.read_text())
                    self.answer(self.bridge / "inbox", request.name)
                    return


def publish(inbox, name, data=""):
    """Put a file in the inbox whole, as the bridge moves a finished upload into place."""
    upload = inbox / f".upload-{name}"
    upload.write_text(data)
    upload.replace(inbox / name)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.bridge = self.home.path / ".agentkit/macbridge"

    def fetch(self, answer, path=GONE):
        mac = Mac(self.home, answer)
        mac.start()
        try:
            done = self.home.ak("fetch", path, env={"AK_FETCH_TIMEOUT": "30"})
        finally:
            mac.stop.set()
            mac.join(5)
        return done, mac

    def left(self, folder):
        return sorted(path.name for path in (self.bridge / folder).iterdir())

    def test_a_path_this_host_lacks_is_asked_of_the_mac_and_the_copy_it_sends_is_printed(self):
        done, mac = self.fetch(lambda inbox, ident: publish(inbox, f"{ident}.pdf", "%PDF-1.4\n"),
                               REPORT)
        self.assertEqual(mac.asked, {"path": REPORT, "basename": "report.pdf"})
        self.assertEqual(done.code, 0, done.err)
        copy = self.bridge / "inbox" / f"{mac.request}.pdf"
        self.assertEqual(done.out, f"{copy}\n")
        self.assertEqual(copy.read_text(), "%PDF-1.4\n")
        self.assertEqual(self.left("requests"), [])
        self.assertEqual(self.left("inbox"), [copy.name])

    def test_an_error_the_mac_sends_back_fails_the_fetch_with_its_reason(self):
        done, _ = self.fetch(lambda inbox, ident: publish(inbox, f".{ident}.error",
                                                          "permission denied\n"))
        self.assertEqual((done.code, done.out, done.err),
                         (1, "", f"ak fetch: {GONE}: permission denied\n"))
        self.assertEqual(self.left("requests"), [])
        self.assertEqual(self.left("inbox"), [])

    def test_a_file_the_mac_no_longer_has_fails_the_fetch(self):
        done, _ = self.fetch(lambda inbox, ident: publish(inbox, f"{ident}.missing"))
        self.assertEqual((done.code, done.out, done.err),
                         (1, "", f"ak fetch: the Mac no longer has that file: {GONE}\n"))
        self.assertEqual(self.left("requests"), [])
        self.assertEqual(self.left("inbox"), [])

    def test_a_file_whose_own_name_ends_in_missing_is_delivered_behind_the_macs_receipt(self):
        # `.missing` is also the gone mark's name, so the Mac sends a receipt before the file.
        def answer(inbox, ident):
            publish(inbox, f".{ident}.ready")
            publish(inbox, f"{ident}.missing", "kept\n")
        done, mac = self.fetch(answer, "/Users/acme/notes.missing")
        self.assertEqual(done.code, 0, done.err)
        copy = self.bridge / "inbox" / f"{mac.request}.missing"
        self.assertEqual(done.out, f"{copy}\n")
        self.assertEqual(self.left("inbox"), [copy.name])

    def test_a_fetch_nobody_answers_gives_up_at_its_timeout_and_leaves_no_request(self):
        done = self.home.ak("fetch", GONE, env={"AK_FETCH_TIMEOUT": "0"})
        self.assertEqual((done.code, done.out, done.err), (1, "", NO_ANSWER))
        self.assertEqual(self.left("requests"), [])

    def test_the_bridge_folders_are_the_owners_alone(self):
        # What the owner drags in may be private papers, and the host may have other users.
        self.home.ak("fetch", GONE, env={"AK_FETCH_TIMEOUT": "0"})
        for folder in (self.bridge, self.bridge / "requests", self.bridge / "inbox"):
            with self.subTest(folder.name):
                self.assertEqual(folder.stat().st_mode & 0o777, 0o700)

    def test_a_path_this_host_has_is_printed_whole_and_each_path_answers_on_its_own(self):
        notes = self.home.write("code/acme/notes.txt", "hi\n")
        done = self.home.ak("fetch", "notes.txt", GONE, cwd=notes.parent,
                            env={"AK_FETCH_TIMEOUT": "0"})
        self.assertEqual((done.code, done.out, done.err), (1, f"{notes}\n", NO_ANSWER))

    def test_a_fetch_it_cannot_make_says_why(self):
        timeout = "ak fetch: AK_FETCH_TIMEOUT must be a finite, non-negative number\n"
        # A tab or newline cannot travel in the line the Mac reads the path from.
        unsendable = "ak fetch: a file path must be non-empty and contain no tabs or newlines\n"
        cases = [((), None, 2, USAGE), (("--serve", "x.pdf"), None, 2, USAGE),
                 (("x.pdf",), {"AK_FETCH_TIMEOUT": "-1"}, 2, timeout),
                 (("x.pdf",), {"AK_FETCH_TIMEOUT": "nan"}, 2, timeout),
                 (("/Users/acme/a\tb.pdf",), None, 1, unsendable)]
        for args, env, code, err in cases:
            with self.subTest(args=args, env=env):
                done = self.home.ak("fetch", *args, env=env)
                self.assertEqual((done.code, done.out, done.err), (code, "", err))


if __name__ == "__main__":
    unittest.main()
