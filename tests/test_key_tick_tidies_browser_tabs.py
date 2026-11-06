"""The tick closes the shared browser's idle tabs, never its last one, and an unreachable browser
adds nothing to what it says.

Each tick asks Chromium's DevTools endpoint which targets are open, and by the record of each
tab's url and title as last seen (`~/.agentkit/state/browser-tabs.json`, which `ak browser
status` reads too) closes a tab unchanged for AK_BROWSER_TAB_IDLE_MIN minutes, 60 unless set,
but for the tab changed last; past AK_BROWSER_TAB_CAP open tabs, 12 unless set, the oldest by
last change close too.  The last tab never closes and frames and workers are never touched.
What a tick says is each line the class's first tick did not print, what a pass took aside: that
tick has the browser up and nothing to close.  A tick closing tabs says one line at most; with no
browser listening, or one answering garbage, it exits 0 and says none.  No line is searched for a
word, as the tick prints paths and a path can hold any word; so a program telling of the browser
on every tick, the first one too, passes here.  The browser is the test's stand-in at the address
ak's browser uses, 127.0.0.1:9222, so the whole file runs in one box (`rerun_boxed`) with a
network of its own: the host's shared browser there holds other sessions' tabs.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and this test fails
against `/bin/false`.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import BOXED, Home, rerun_boxed

RECORD = ".agentkit/state/browser-tabs.json"
# what a pass took is the host's load, not anything the browser said
TOOK = re.compile(r" took \d+(\.\d+)? s$")


class DevTools(ThreadingHTTPServer):
    """Chromium's DevTools endpoint on 127.0.0.1:9222, answering `targets` to a listing, or
    `garbage` as it is to everything; it closes a target asked to and keeps its id in `closed`."""

    def __init__(self, targets=(), garbage=None):
        self.targets, self.garbage, self.closed = list(targets), garbage, []
        super().__init__(("127.0.0.1", 9222), Answer)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.shutdown()
        self.server_close()


class Answer(BaseHTTPRequestHandler):
    def do_GET(self):
        browser, path = self.server, self.path.split("?")[0]
        body = {"/json": browser.targets, "/json/list": browser.targets,
                "/json/version": {"Browser": "Chrome/140.0.7339.80"}}.get(path)
        if path.startswith("/json/close/"):
            closing = path.removeprefix("/json/close/")
            browser.closed.append(closing)
            browser.targets = [found for found in browser.targets if found["id"] != closing]
            body = b"Target is closing"
        if browser.garbage is not None:
            body = browser.garbage
        self.send_response(404 if body is None else 200)
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_PUT = do_GET     # Chromium takes either

    def log_message(self, *_args):
        pass


def target(name, kind="page", **changed):
    """An open target as DevTools lists it; `changed` its url or title since the record."""
    return {"id": name, "type": kind, "title": f"Acme {name}", "url": f"https://acme.test/{name}",
            **changed}


@unittest.skipUnless(BOXED, "no bwrap able to give the test a network of its own")
class TickTidiesBrowserTabs(unittest.TestCase):
    own = None      # what the first tick printed: lines any tick may print

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus"])      # no audit seat for the tick to open
        # One tab long idle and past a cap of one, beside a frame and a worker as idle: a tick
        # with nothing to close, so all it prints is the tick's own.
        cls.closed_first = cls.tick(
            [target("only"), target("frame", "iframe"), target("worker", "service_worker")],
            {"only": 180, "frame": 180, "worker": 180}, AK_BROWSER_TAB_CAP="1")[1]

    @classmethod
    def tick(cls, targets=None, unchanged=(), garbage=None, **env):
        """One tick, exiting 0, over a browser with `targets` open, or answering `garbage`, or
        (neither) none listening; the record holds each target named in `unchanged` at its first
        url and title that many minutes ago (200 at most), and saw them first in the reverse
        order, so neither order stands for the other.  What it said, each line the first tick
        did not print, and each target it closed."""
        now = time.time()
        cls.home.write(RECORD, {name: {"first_seen": now - 60 * (400 - minutes),
                                       "last_change": now - 60 * minutes,
                                       "url": target(name)["url"], "title": target(name)["title"]}
                                for name, minutes in dict(unchanged).items()})
        if targets is None and garbage is None:
            done, closed = cls.home.ak("watch", env=env), []
        else:
            with DevTools(targets or (), garbage) as browser:
                done, closed = cls.home.ak("watch", env=env), browser.closed
        assert done.code == 0, done.out + done.err
        lines = [line for line in (done.out + done.err).splitlines() if not TOOK.search(line)]
        cls.own = lines if cls.own is None else cls.own
        return [line for line in lines if line not in cls.own], sorted(closed)

    def closes(self, *args, **env):
        """The targets a tick closed, having told of it in one line at most."""
        said, closed = self.tick(*args, **env)
        self.assertLessEqual(len(said), 1, said)
        return closed

    def test_the_last_tab_and_any_frame_or_worker_stay_however_idle(self):
        self.assertEqual(self.closed_first, [])

    def test_a_tab_whose_url_and_title_held_for_an_hour_closes_and_a_frame_or_worker_not(self):
        self.assertEqual(self.closes(
            [target("recent"), target("retitled", title="Acme retitled on"),
             target("navigated", url="https://acme.test/navigated/on"), target("stale"),
             target("frame", "iframe"), target("worker", "service_worker")],
            {"recent": 50, "retitled": 180, "navigated": 180, "stale": 70, "frame": 180,
             "worker": 180}), ["stale"])

    def test_the_tab_changed_last_stays_though_all_are_idle_past_the_minutes_set(self):
        self.assertEqual(self.closes([target("last"), target("first"), target("second")],
                                     {"first": 50, "second": 40, "last": 30},
                                     AK_BROWSER_TAB_IDLE_MIN="20"), ["first", "second"])

    def test_past_the_cap_the_oldest_by_last_change_close_down_to_it(self):
        self.assertEqual(self.closes(
            [target(name) for name in ("m10", "m50", "m20", "m40", "m30")]
            + [target("frame", "iframe"), target("worker", "shared_worker")],
            {"m10": 10, "m50": 50, "m20": 20, "m40": 40, "m30": 30, "frame": 55, "worker": 55},
            AK_BROWSER_TAB_CAP="3"), ["m40", "m50"])

    def test_no_browser_listening_costs_the_tick_nothing(self):
        self.assertEqual(self.tick(unchanged={"stale": 180}), ([], []))

    def test_a_browser_answering_garbage_costs_the_tick_nothing(self):
        for garbage in (b"<html>502 Bad Gateway</html>", b'{"targets": "none"}'):
            with self.subTest(garbage):
                self.assertEqual(self.tick(unchanged={"stale": 180}, garbage=garbage), ([], []))


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
