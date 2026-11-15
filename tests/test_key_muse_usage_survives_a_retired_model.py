"""Muse's usage outlives the model it is asked with: answered `model_not_found`, the probe asks
once more with its harness's `[check]` model and effort, and only then."""

import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[1]
CHECK = tomllib.loads((REPO / "adapters" / "muse.toml").read_text())["check"]
RETIRED = "muse-wonder-full-1.0"


class Meta(http.server.BaseHTTPRequestHandler):
    """Meta's endpoint on the loopback (`AK_MUSE_URL`): logs each request and answers by the
    model asked, `answers` {model: status}, 404 for any other."""

    def do_POST(self):
        asked = json.loads(self.rfile.read(int(self.headers["content-length"])))
        self.server.requests.append({"path": self.path, **asked})
        status = self.server.answers.get(asked["model"], 404)
        body = {200: "data: " + json.dumps(self.server.frame) + "\n",
                404: '{"error":{"code":"model_not_found","message":"no such model"}}',
                500: '{"error":{"code":"server_error"}}'}[status].encode()
        self.send_response(status)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class RetiredModel(unittest.TestCase):
    def usage(self, answers):
        """`adapters/muse.sh usage` in a throwaway home: its JSON and the requests Meta saw."""
        with tempfile.TemporaryDirectory(prefix="ak-test-muse-retired-") as tmp:
            root = Path(tmp)
            (root / "home" / ".agentkit").mkdir(parents=True)
            (root / "home" / ".agentkit" / "config.toml").write_text(f'''
[models.wonder]
harness = "muse"
model = "{RETIRED}"
effort = "xhigh"
provider = "meta"

[providers.meta]
mode = "subscription"
usage_model = "wonder"
usage_effort = "low"
''')
            stamp = int(time.time()) + 3600
            self.frame = {"type": "response.subscription_usage", "subscription": {
                "window": {"used_percent": 7, "resets_at": stamp, "window_duration_mins": 300},
                "weekly": {"used_percent": 41, "resets_at": stamp + 100}}}
            meta = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Meta)
            meta.answers, meta.frame, meta.requests = answers, self.frame, []
            threading.Thread(target=meta.serve_forever, daemon=True).start()
            env = {"HOME": str(root / "home"), "PATH": os.environ["PATH"],
                   "PYTHONDONTWRITEBYTECODE": "1", "META_API_KEY": "fixture-key",
                   "AK_MUSE_URL": f"http://127.0.0.1:{meta.server_address[1]}"}
            try:
                proc = subprocess.run([str(REPO / "adapters" / "muse.sh"), "usage"], env=env,
                                      capture_output=True, text=True, timeout=60)
            finally:
                meta.shutdown()
                meta.server_close()
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout), meta.requests

    def asked(self, requests):
        return [(r["model"], r["reasoning"]["effort"]) for r in requests]

    def test_a_retired_model_is_asked_again_with_the_check_model(self):
        data, requests = self.usage({CHECK["model"]: 200})
        self.assertIsNone(data["error"])
        self.assertEqual(data["meters"], [
            {"name": "window", "used": 7, "resets_at": self.frame["subscription"]["window"]["resets_at"],
             "window_secs": 18000},
            {"name": "weekly", "used": 41, "resets_at": self.frame["subscription"]["weekly"]["resets_at"],
             "window_secs": 604800}])
        self.assertEqual(self.asked(requests), [(RETIRED, "low"), (CHECK["model"], CHECK["effort"])])
        self.assertEqual({r["path"] for r in requests}, {"/v1/responses"})

    def test_a_served_model_is_asked_once(self):
        data, requests = self.usage({RETIRED: 200})
        self.assertIsNone(data["error"])
        self.assertEqual(self.asked(requests), [(RETIRED, "low")])

    def test_both_retired_reads_as_today(self):
        data, requests = self.usage({})
        self.assertEqual(data["meters"], [])
        self.assertEqual(data["error"], "unknown: responses probe returned HTTP 404")
        self.assertEqual(self.asked(requests), [(RETIRED, "low"), (CHECK["model"], CHECK["effort"])])

    def test_any_other_failure_is_asked_once(self):
        data, requests = self.usage({RETIRED: 500, CHECK["model"]: 200})
        self.assertEqual(data["error"], "unknown: responses probe returned HTTP 500")
        self.assertEqual(self.asked(requests), [(RETIRED, "low")])


if __name__ == "__main__":
    unittest.main()
