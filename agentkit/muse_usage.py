"""Cached Muse subscription meters from one bounded model request."""

import fcntl
import http.client
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, usage_probe
from agentkit.harness import load as harness_plugin

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "muse"
AUTH = CONFIG / "auth.json"
CACHE_TTL = 600     # one billed request in ten minutes, however often the menu asks


def left(reserve=0.0):
    return max(0.0, float(os.environ[usage_probe.WORK_DEADLINE_ENV]) - time.monotonic() - reserve)


def auth_file():
    """(api_key or None, api base origin or None) from Muse's file credential backend."""
    try:
        with open(AUTH) as fh:
            meta = json.load(fh).get("providers", {}).get("meta", {})
    except Exception:
        return None, None
    key = meta.get("api_key")
    base = meta.get("api_base_url")
    return (key if isinstance(key, str) and key else None,
            base if isinstance(base, str) and base.startswith("https://") else None)


class _Capture(http.server.BaseHTTPRequestHandler):
    """Answers Muse's product calls just well enough to see one Authorization header."""
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        got = self.headers.get("authorization", "")
        if got.lower().startswith("bearer ") and not self.server.token:
            self.server.token = got.split(" ", 1)[1].strip()
            self.server.seen.set()
        body = b'{"object":"list","data":[]}' if "models" in self.path else b"{}"
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *a):
        pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # a traceback from the credential bridge must never expose request data


def key_from_muse():
    """Start muse against a loopback base URL and lift the bearer off its first product call."""
    muse = shutil.which("muse") or os.path.expanduser("~/.local/bin/muse")
    if not os.path.exists(muse):
        return None, "muse is not installed"
    try:
        srv = _Server(("127.0.0.1", 0), _Capture)
    except OSError:
        return None, "could not open a loopback listener"
    srv.token = None
    srv.seen = threading.Event()
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=.05), daemon=True).start()
    port = srv.server_address[1]

    data_home = tempfile.mkdtemp(prefix="muse-usage-")
    env = dict(os.environ,
               MUSE_NO_AUTO_UPDATE="1",
               XDG_DATA_HOME=data_home,
               NO_COLOR="1")
    env.pop("META_API_KEY", None)  # the account login is the credential we are after
    proc = None
    try:
        # No tty: the TUI still runs its startup product fetches, then exits by itself.  --yolo
        # settles workspace trust from the run flag; without it the throwaway cwd raises a trust
        # prompt that cannot render headless, and muse quits before it reaches the catalog.
        proc = subprocess.Popen(
            [muse, "--provider", "meta", "--yolo",
             "--base-url", "http://127.0.0.1:%d" % port],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, cwd=data_home)
        if not srv.seen.wait(timeout=left() / 2):
            return None, "credential extraction timed out (logged in?)"
        return srv.token, None
    except OSError:
        return None, "could not start muse"
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=min(.2, left()))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=max(.01, left()))
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(data_home, ignore_errors=True)


def parse_frame(payload):
    sub = payload.get("subscription") or {}
    meters = []
    win = sub.get("window")
    if isinstance(win, dict) and win.get("used_percent") is not None:
        mins = win.get("window_duration_mins")
        meters.append({"name": "window",
                       "used": max(0, min(100, int(round(float(win["used_percent"]))))),
                       "resets_at": int(win.get("resets_at") or 0),
                       "window_secs": int(mins) * 60 if mins else 18000})
    week = sub.get("weekly")
    if isinstance(week, dict) and week.get("used_percent") is not None:
        meters.append({"name": "weekly",
                       "used": max(0, min(100, int(round(float(week["used_percent"]))))),
                       "resets_at": int(week.get("resets_at") or 0),
                       "window_secs": 604800})
    return meters


def exhausted(body):
    """A subscription 429 names its own reset; report the window as spent until then.  A bare
    capacity 429 ("Service temporarily unavailable") carries no stamp and is not exhaustion."""
    m = re.search(r"resets\s+(?:at\s+)?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z", body)
    if not m:
        return None
    import calendar, datetime
    try:
        when = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    stamp = calendar.timegm(when.timetuple())
    return [{"name": "window", "used": 100,
             "resets_at": stamp, "window_secs": 604800 if stamp - time.time() > 18000 else 18000}]


def model_policy():
    """The probe uses a config.toml model key and effort, with no catalogue fallback.

    Whether that entry is this probe's to run is its harness's own answer
    (`agentkit/harness/muse.py`): a model on any other harness has no policy here to satisfy.
    """
    cfg = config.load()
    provider = cfg["providers"]["meta"]
    name = provider.get("usage_model") or config.provider_harness(cfg, "meta")[1]
    entry = config.model(cfg, name)
    effort = provider.get("usage_effort", entry["effort"])
    if (entry["provider"] != "meta"
            or not harness_plugin(entry["harness"]).usage_policy(entry, effort)):
        raise config.Error("invalid Muse usage policy")
    return entry["model"], effort


def probe(key, origin, model, effort):
    body = json.dumps({"model": model,
                       "input": "x",
                       "max_output_tokens": 16,   # the API's documented floor
                       "stream": True,
                       "store": False,
                       "reasoning": {"effort": effort}}).encode()
    host = origin.split("://", 1)[1].rstrip("/")
    conn = http.client.HTTPSConnection(host, 443, timeout=max(.001, left()))
    try:
        conn.request("POST", "/v1/responses", body=body, headers={
            "authorization": "Bearer " + key,
            "content-type": "application/json",
            "accept": "text/event-stream",
        })
        resp = conn.getresponse()
        if resp.status != 200:
            text = resp.read(4096).decode("utf-8", "replace").strip()
            if resp.status == 429:
                meters = exhausted(text)
                if meters:
                    return meters, None
            return None, "responses probe returned HTTP %d" % resp.status
        for raw in resp:
            if left() <= 0:
                return None, "timed out reading the response stream"
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                payload = json.loads(line[5:].strip())
            except Exception:
                continue
            if isinstance(payload, dict) and (payload.get("type") == "response.subscription_usage"
                                              or "subscription" in payload):
                meters = parse_frame(payload)
                # the frame is terminal; nothing after it is worth waiting for
                return (meters, None) if meters else (None, "subscription frame carried no meters")
        return None, "no response.subscription_usage frame in the stream"
    except TimeoutError:
        return None, "responses probe timed out"
    except Exception:
        return None, "responses probe failed"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def fresh():
    try:
        model, effort = model_policy()
    except (config.Error, KeyError, TypeError, ValueError):
        return result(error="invalid Muse usage policy in ~/.agentkit/config.toml")
    key, base = auth_file()
    origin = "https://api.meta.ai"
    if base:
        parts = base.split("://", 1)
        origin = parts[0] + "://" + parts[1].split("/", 1)[0]
    key = os.environ.get("META_API_KEY") or key
    if not key:
        if not os.path.exists(AUTH):
            return result(error="not logged in: Muse auth file is missing")
        key, err = key_from_muse()
        if not key:
            return result(error=err or "could not obtain a Meta credential")
    if left() <= 0:
        return result(error="Muse usage probe timed out")
    meters, err = probe(key, origin, model, effort)
    meters = [meter for meter in meters or [] if meter["resets_at"] > time.time()]
    return result(meters, err or (None if meters else "no current subscription meters"))


def result(meters=None, error=None):
    return {"provider": "meta", "meters": meters or [],
            "error": "unknown: " + error if error else None}


def read(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, data):
    # A private atomic file also prevents overlapping readers from seeing a partial result.
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".",
                                     delete=False) as fh:
        tmp = Path(fh.name)
        try:
            json.dump({**data, "fetched_at": time.time()}, fh)
            fh.close()
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def cached():
    state = config.STATE
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache = state / "usage-meta-probe.json"
    # Claim before spending a request: a killed probe or a second reader cannot cause a
    # fresh request inside the TTL. All outcomes, including unknown, use the same cache, and so
    # does a meter that has reset since: the TTL is between paid requests, and a window that
    # rolls over inside it is dropped by `ak usage` until the next one reads the new window.
    with (state / "usage-meta-probe.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = time.time()
        recorded = read(state / "usage-meta.json")
        meters = [m for m in recorded.get("meters", []) if m.get("resets_at", 0) > now]
        if meters:
            return result(meters)
        data = read(cache)
        if (0 <= now - data.get("fetched_at", 0) < CACHE_TTL
                and isinstance(data.get("meters"), list)):
            return {key: data.get(key) for key in ("provider", "meters", "error")}
        save(cache, result(error="Muse usage probe did not complete within its budget"))
        data = fresh()
        save(cache, data)
        return data


if __name__ == "__main__":
    if usage_probe.WORK_DEADLINE_ENV not in os.environ:
        argv, env = usage_probe.command([sys.executable, str(Path(__file__).resolve())])
        os.execve(sys.executable, argv, env)
    try:
        print(json.dumps(cached()))
    except Exception:
        print(json.dumps(result(error="Muse usage probe failed")))
