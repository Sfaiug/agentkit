"""v5ae: the shared browser stays small, because the tick closes tabs nobody uses.

Offline: a fake CDP HTTP server on a random loopback port answers /json/list,
/json/version and /json/close/<id>, and browser.CDP points at it. All writes stay
in a temporary state directory. The real 127.0.0.1:9222 is never touched.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import browser, config, notify, orch, run as run_mod, usage, watch

NOW = 1_750_000_000.0


class FakeCDP:
    """A Chromium-shaped CDP HTTP endpoint: list, version, and close-by-id."""

    def __init__(self, tabs):
        self.tabs = list(tabs)
        self.closed = []
        self.lock = threading.Lock()

        store = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/json/version":
                    body = json.dumps({"Browser": "Fake Chromium/1.0",
                                       "Protocol-Version": "1.3"}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/json/list":
                    with store.lock:
                        body = json.dumps(store.tabs).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/json/close/"):
                    target = self.path[len("/json/close/"):]
                    with store.lock:
                        found = next((tab for tab in store.tabs
                                      if tab.get("id") == target), None)
                        if found is not None:
                            store.tabs.remove(found)
                            store.closed.append(target)
                    if found is None:
                        self.send_response(404)
                        self.end_headers()
                    else:
                        body = b"Target closed"
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def ids(self):
        with self.lock:
            return [tab["id"] for tab in self.tabs]


def page(target_id, title, url="https://example.com/", kind="page"):
    return {"id": target_id, "title": title, "url": url, "type": kind,
            "webSocketDebuggerUrl": f"ws://127.0.0.1/devtools/page/{target_id}"}


class V5AE(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5ae-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_BROWSER_TAB_IDLE_MIN": "60", "AK_BROWSER_TAB_CAP": "12",
        }))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.fake = None
        self.logs = []

    def serve(self, tabs):
        self.fake = FakeCDP(tabs).start()
        self.addCleanup(self.fake.stop)
        self.stack.enter_context(patch.object(browser, "CDP", self.fake.url))
        return self.fake

    def records(self):
        try:
            return json.loads(browser.tab_records_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write_records(self, entries):
        path = browser.tab_records_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")

    def test_v5ae_idle_tab_closed_and_newest_kept(self):
        self.serve([page("A", "Old alpha tab with a very long title indeed, yes",
                         "https://a.example/"),
                    page("B", "Old beta", "https://b.example/"),
                    page("C", "Newest gamma", "https://c.example/"),
                    page("F", "captcha frame", "https://f.example/", kind="iframe")])
        self.write_records({
            "A": {"first_seen": NOW - 4 * 3600, "last_change": NOW - 3 * 3600,
                  "url": "https://a.example/", "title": "Old alpha tab with a very long title indeed, yes"},
            "B": {"first_seen": NOW - 3 * 3600, "last_change": NOW - 2 * 3600,
                  "url": "https://b.example/", "title": "Old beta"},
            "C": {"first_seen": NOW - 61 * 60, "last_change": NOW - 61 * 60,
                  "url": "https://c.example/", "title": "Newest gamma"},
        })
        browser.tidy(self.logs.append, now=NOW)
        self.assertEqual(sorted(self.fake.closed), ["A", "B"])
        self.assertEqual(self.fake.ids(), ["C", "F"])
        self.assertEqual(len(self.logs), 1)
        self.assertTrue(self.logs[0].startswith("browser: closed 2 idle tabs (3 → 1): "),
                        self.logs[0])
        self.assertIn("Old alpha tab with a very long title i", self.logs[0])
        self.assertNotIn("F", self.fake.closed)
        self.assertEqual(sorted(self.records()), ["C"])

    def test_v5ae_recently_changed_tab_kept(self):
        self.serve([page("X", "Fresh title", "https://x.example/"),
                    page("Y", "Other tab", "https://y.example/")])
        self.write_records({
            "X": {"first_seen": NOW - 3600, "last_change": NOW - 5 * 60,
                  "url": "https://x.example/", "title": "Fresh title"},
            "Y": {"first_seen": NOW - 3600, "last_change": NOW - 5 * 60,
                  "url": "https://y.example/", "title": "Other tab"},
        })
        browser.tidy(self.logs.append, now=NOW)
        self.assertEqual(self.fake.closed, [])
        self.assertEqual(self.logs, [])
        kept = self.records()
        self.assertEqual(kept["X"]["last_change"], NOW - 5 * 60)
        self.assertEqual(kept["X"]["title"], "Fresh title")

    def test_v5ae_over_cap_closes_oldest_first(self):
        tabs = [page(f"T{i:02d}", f"Tab {i}", f"https://t{i}.example/") for i in range(15)]
        self.serve(tabs)
        self.write_records({
            f"T{i:02d}": {"first_seen": NOW - (i + 1) * 60, "last_change": NOW - (i + 1) * 60,
                          "url": f"https://t{i}.example/", "title": f"Tab {i}"}
            for i in range(15)
        })
        browser.tidy(self.logs.append, now=NOW)
        self.assertEqual(sorted(self.fake.closed), ["T12", "T13", "T14"])
        self.assertEqual(len(self.fake.ids()), 12)
        self.assertEqual(len(self.logs), 1)
        self.assertTrue(self.logs[0].startswith("browser: closed 3 idle tabs (15 → 12): "),
                        self.logs[0])
        self.assertEqual(len(self.records()), 12)

    def test_v5ae_first_tick_tiebreak_closes_last_listed(self):
        tabs = [page(f"N{i:02d}", f"New {i}", f"https://n{i}.example/") for i in range(13)]
        self.serve(tabs)
        browser.tidy(self.logs.append, now=NOW)
        self.assertEqual(self.fake.closed, ["N12"])
        self.assertEqual(len(self.fake.ids()), 12)
        self.assertEqual(len(self.logs), 1)
        self.assertTrue(self.logs[0].startswith("browser: closed 1 idle tabs (13 → 12): "),
                        self.logs[0])

    def test_v5ae_single_tab_never_closed(self):
        self.serve([page("S", "Only tab", "https://s.example/")])
        self.write_records({
            "S": {"first_seen": NOW - 24 * 3600, "last_change": NOW - 10 * 3600,
                  "url": "https://s.example/", "title": "Only tab"},
        })
        browser.tidy(self.logs.append, now=NOW)
        self.assertEqual(self.fake.closed, [])
        self.assertEqual(self.logs, [])
        self.assertEqual(self.fake.ids(), ["S"])
        self.assertEqual(sorted(self.records()), ["S"])

    def test_v5ae_unreachable_cdp_returns_quietly(self):
        self.stack.enter_context(patch.object(browser, "CDP", "http://127.0.0.1:1"))
        self.assertIsNone(browser.tidy(self.logs.append, now=NOW))
        self.assertLessEqual(len(self.logs), 1)
        self.assertFalse(browser.tab_records_path().exists())

    def test_v5ae_status_shows_idle_age_and_summary(self):
        self.serve([page("P", "Young tab", "https://p.example/"),
                    page("Q", "Ancient tab", "https://q.example/")])
        moment = time.time()
        self.write_records({
            "P": {"first_seen": moment - 12 * 60, "last_change": moment - 12 * 60,
                  "url": "https://p.example/", "title": "Young tab"},
            "Q": {"first_seen": moment - 3 * 3600, "last_change": moment - 3 * 3600,
                  "url": "https://q.example/", "title": "Ancient tab"},
        })
        out = io.StringIO()
        with patch.object(browser, "unit_states", return_value=None), \
                redirect_stdout(out):
            self.assertEqual(browser.status([]), 0)
        body = out.getvalue()
        self.assertIn("idle 12m", body)
        self.assertIn("idle 3h", body)
        self.assertIn("tabs       2 open (cap 12; a tab idle 60 min is closed by ak watch)",
                      body)


    def test_v5ae_tick_calls_tidy_once_skips_dry_run_and_stays_offline(self):
        # The tick must stay offline here: no collector over the real HOME and no tmux
        # outside -L agentkit-test may escape, so the maintenance pass is fully stubbed.
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        self.stack.enter_context(patch.object(subprocess, "run",
                                              side_effect=AssertionError("subprocess")))
        healthy = [patch.object(watch, "gh_json", return_value=({"login": "me"}, "")),
                   patch.object(watch, "health"),
                   patch.object(watch, "recover_runs"),
                   patch.object(watch, "incoming"),
                   patch.object(watch, "outgoing"),
                   patch.object(watch, "save_state"),
                   patch.object(usage, "collect", return_value={}),
                   patch.object(run_mod, "run_dirs", return_value=[]),
                   patch.object(run_mod, "schedule_gc"),
                   patch.object(orch, "stamp"),
                   patch.object(orch, "sweep"),
                   patch.object(notify, "retry_pending"),
                   patch.object(notify, "tick_cards")]
        for handle in healthy:
            self.stack.enter_context(handle)
        with patch.object(watch.browser, "tidy") as tidy:
            self.assertEqual(watch.main([]), 0)
            self.assertEqual(tidy.call_count, 1)
        with patch.object(watch.browser, "tidy") as tidy:
            self.assertEqual(watch.main(["--dry-run"]), 0)
            tidy.assert_not_called()
        # A tick whose gh is logged out still tidies, because the tidy owes GitHub nothing:
        # offline fixtures may forbid every urlopen call and still see none.
        with patch.object(watch, "gh_json", return_value=(None, "offline")), \
                patch.object(watch.browser, "tidy") as tidy, \
                patch.object(notify.urllib.request, "urlopen") as request:
            said = io.StringIO()
            with redirect_stdout(said):
                self.assertEqual(watch.main([]), 0)
            self.assertIn("PR checks skipped", said.getvalue())
            self.assertEqual(tidy.call_count, 1)
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
