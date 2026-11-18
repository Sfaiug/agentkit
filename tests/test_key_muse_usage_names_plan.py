"""Muse's usage probe names the plan its frame carries: `adapters/muse-usage.sh` prints `plan`,
the name adapters/muse.toml's [tiers] gives the frame's `subscription.tier` (27681527378179523 is
High Usage), null for a tier it does not name or a frame with none, and no `plan` at all for an
answer that read no frame, a spent 429."""

import datetime
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

REPO = Path(__file__).resolve().parents[1]


class Meta(http.server.BaseHTTPRequestHandler):
    """Meta's endpoint on the loopback (`AK_MUSE_URL`), answering every request with
    `self.server.answer`: (status, body)."""

    def do_POST(self):
        self.rfile.read(int(self.headers["content-length"]))
        status, body = self.server.answer
        self.send_response(status)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


class MuseUsageNamesPlan(unittest.TestCase):
    def usage(self, status, body):
        """`adapters/muse-usage.sh`'s JSON in a throwaway home, Meta answering `status`, `body`."""
        with tempfile.TemporaryDirectory(prefix="ak-test-muse-plan-") as tmp:
            home = Path(tmp)
            (home / ".agentkit").mkdir()
            (home / ".agentkit" / "config.toml").write_text('''
[models.acme]
harness = "muse"
model = "muse-acme-1"
effort = "low"
provider = "meta"

[providers.meta]
mode = "subscription"
usage_model = "acme"
''')
            meta = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Meta)
            meta.answer = status, body
            threading.Thread(target=meta.serve_forever, daemon=True).start()
            env = {"HOME": str(home), "PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1",
                   "META_API_KEY": "fixture-key",
                   "AK_MUSE_URL": f"http://127.0.0.1:{meta.server_address[1]}"}
            try:
                proc = subprocess.run([str(REPO / "adapters" / "muse-usage.sh")], env=env,
                                      capture_output=True, text=True, timeout=60)
            finally:
                meta.shutdown()
                meta.server_close()
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)

    def frame(self, **tier):
        stamp = int(time.time()) + 3600
        frame = {"type": "response.subscription_usage", "subscription": {
            **tier, "window": {"used_percent": 7, "resets_at": stamp, "window_duration_mins": 300},
            "weekly": {"used_percent": 41, "resets_at": stamp + 100}}}
        data = self.usage(200, "data: " + json.dumps(frame) + "\n\n")
        self.assertIsNone(data["error"])
        self.assertEqual([meter["used"] for meter in data["meters"]], [7, 41])
        return data

    def test_the_tier_the_table_names_is_its_plan(self):
        self.assertEqual(self.frame(tier="27681527378179523")["plan"], "High Usage")

    def test_a_tier_it_does_not_name_is_no_plan(self):
        self.assertIsNone(self.frame(tier="12345678901234567")["plan"])

    def test_a_frame_with_no_tier_is_no_plan(self):
        data = self.frame()
        self.assertIn("plan", data)
        self.assertIsNone(data["plan"])

    def test_a_spent_429_reads_no_frame_and_names_no_plan(self):
        resets = datetime.datetime.fromtimestamp(time.time() + 3600, datetime.timezone.utc)
        data = self.usage(429, '{"error":{"message":"Usage limit reached; resets at '
                               + resets.strftime("%Y-%m-%dT%H:%M:%S") + 'Z"}}')
        self.assertEqual([meter["used"] for meter in data["meters"]], [100])
        self.assertNotIn("plan", data)


if __name__ == "__main__":
    unittest.main()
