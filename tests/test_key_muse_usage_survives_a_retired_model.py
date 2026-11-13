"""Muse's usage outlives the model it is asked with: answered `model_not_found`, the probe asks
once more with its harness's `[check]` model and effort, and only then."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[1]
CHECK = tomllib.loads((REPO / "adapters" / "muse.toml").read_text())["check"]
RETIRED = "muse-wonder-full-1.0"

# Loaded by every Python the adapter starts: Meta's endpoint is a fake that logs each request
# and answers by the model asked, and no socket leaves the box.
NETWORK = r'''
import http.client, io, json, os, socket
def offline(sock, address):
    raise AssertionError("external network forbidden")
socket.socket.connect = offline
class Connection:
    def __init__(self, host, port, timeout):
        self.host = host
    def request(self, method, path, body, headers):
        self.asked = json.loads(body)
        with open(os.environ["MUSE_REQUESTS"], "a") as fh:
            fh.write(json.dumps({"host": self.host, "path": path, **self.asked}) + "\n")
    def getresponse(self):
        status = json.loads(os.environ["MUSE_ANSWERS"]).get(self.asked["model"], 404)
        body = {200: os.environ["MUSE_FRAME"],
                404: '{"error":{"code":"model_not_found","message":"no such model"}}',
                500: '{"error":{"code":"server_error"}}'}[status]
        response = io.BytesIO(body.encode())
        response.status = status
        return response
    def close(self):
        pass
http.client.HTTPSConnection = Connection
'''


class RetiredModel(unittest.TestCase):
    def usage(self, answers):
        """`adapters/muse.sh usage` in a throwaway home: its JSON and the requests Meta saw."""
        with tempfile.TemporaryDirectory(prefix="ak-test-muse-retired-") as tmp:
            root = Path(tmp)
            (root / "site").mkdir()
            (root / "site" / "sitecustomize.py").write_text(NETWORK)
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
            env = {"HOME": str(root / "home"), "PATH": os.environ["PATH"],
                   "PYTHONPATH": str(root / "site"), "PYTHONDONTWRITEBYTECODE": "1",
                   "META_API_KEY": "fixture-key", "MUSE_REQUESTS": str(root / "requests"),
                   "MUSE_ANSWERS": json.dumps(answers),
                   "MUSE_FRAME": "data: " + json.dumps(self.frame) + "\n"}
            proc = subprocess.run([str(REPO / "adapters" / "muse.sh"), "usage"], env=env,
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            requests = (root / "requests").read_text().splitlines()
            return json.loads(proc.stdout), [json.loads(line) for line in requests]

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
        self.assertEqual({(r["host"], r["path"]) for r in requests}, {("api.meta.ai", "/v1/responses")})

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
