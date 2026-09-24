"""Capture actual harness TUIs against a local error server, via smoke.sh --stall-panes.

No provider is called. Homes, logs and the agentkit-test socket stay under the output folder.
The local server supplies errors; the installed harnesses supply all rendering and chrome.

`--state <prompt|working|dialog>` captures the three seat-state screens instead of a stall:
the composer with nothing running, a turn still in flight (the server holds the request open),
and the harness's own approval dialog -- the only ones reachable with no provider behind them.
"""
import http.server
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config


class Errors(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        model = config.model(cfg, "spark")["model"]
        body = json.dumps({"data": [{"id": model}], "models": [{"id": model}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if state == "working":
            time.sleep(HOLD)     # the turn stays in flight while its pane is captured
        quota = "codex" in self.path or "muse" in self.path
        body = json.dumps({"type": "error", "error": {
            "type": "authentication_error" if auth else "rate_limit_error" if quota else "invalid_request_error",
            "message": "Invalid API key" if auth else
                       "rate limit reached: quota exhausted" if quota else "upstream connect error"}}).encode()
        self.send_response(401 if auth else 429 if quota else 400)
        self.send_header("Retry-After", "0")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


HOLD = 300          # seconds the `working` server holds a request open, well past the capture
STATES = ("prompt", "working", "dialog")
# What says the pane has settled on the screen asked for, per harness and state.
SETTLED = {
    ("claude", "dialog"): ("Do you trust the contents of this directory?",),
    ("codex", "dialog"): ("Hooks need review",),
    ("muse", "dialog"): ("Log in with browser", "Set an API key"),
    ("claude", "working"): ("esc to interrupt",),
    ("codex", "working"): ("esc to interrupt",),
    ("muse", "working"): ("interrupt",),
}

args = sys.argv[2:]
out = Path(sys.argv[1]).resolve()
if not out.is_relative_to(REPO):
    raise SystemExit("the capture output directory must be inside this checkout")
auth = "--auth" in args
state = ""
if "--state" in args:
    at = args.index("--state")
    state = args[at + 1] if at + 1 < len(args) else ""
    if state not in STATES:
        raise SystemExit(f"--state must be one of {', '.join(STATES)}")
    args = args[:at] + args[at + 2:]
if auth and state:
    raise SystemExit("--auth and --state capture different screens; pass one of them")
selected = set(arg for arg in args if arg != "--auth") or {"claude", "codex", "muse"}
if selected - {"claude", "codex", "muse"}:
    raise SystemExit("harness must be claude, codex, or muse")
out.mkdir(parents=True, exist_ok=True)
fd = os.open(out, os.O_RDONLY)
socket = f"/proc/{os.getpid()}/fd/{fd}/agentkit-test"
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Errors)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}"
cfg = config.load()


def tm(*args):
    return subprocess.check_output(["tmux", "-f", "/dev/null", "-L", "agentkit-test", "-S", socket,
                                    *args], text=True,
                                   stderr=subprocess.DEVNULL)


try:
    for harness, alias in (("claude", "opus"), ("codex", "astra"), ("muse", "spark")):
        if harness not in selected:
            continue
        home = out / harness
        home.mkdir(exist_ok=True)
        subprocess.run(["git", "-c", "init.templateDir=", "init", "-q", str(home)], check=True)
        (home / "tmp").mkdir(exist_ok=True)
        (home / ".codex").mkdir(exist_ok=True)
        # The trust dialog is Claude's own approval screen and the only one reachable with no
        # provider behind it, so the `dialog` capture is the one run that does not pre-accept it.
        trusted = state != "dialog" or harness != "claude"
        (home / ".claude.json").write_text(json.dumps({
            "hasCompletedOnboarding": True, "theme": "dark", "bypassPermissionsModeAccepted": True,
            "projects": {str(home): {"hasTrustDialogAccepted": trusted}}}))
        model = config.model(cfg, alias)
        env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
               "XDG_CACHE_HOME": str(home / ".cache"), "CODEX_HOME": str(home / ".codex"),
               "TMPDIR": f"/proc/{os.getpid()}/fd/{fd}/{harness}/tmp",
               "ANTHROPIC_BASE_URL": url, "ANTHROPIC_API_KEY": "fixture-local-only",
               "OPENAI_API_KEY": "fixture-local-only", "META_API_KEY": "fixture-local-only",
               "DISABLE_AUTOUPDATER": "1", "MUSE_NO_AUTO_UPDATE": "1",
               "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "TERM": "xterm-256color"}
        # `prompt` and `dialog` want the screen before any turn, so they send no first message
        ask = [] if state in ("prompt", "dialog") else ["Say OK"]
        if harness == "claude":
            cmd = ["claude", "--model", model["model"],
                   *([] if state == "dialog" else ["--dangerously-skip-permissions"]),
                   "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                   *(["--", *ask] if ask else [])]
        elif harness == "codex":
            cmd = ["codex", "--no-alt-screen", "--yolo", "-m", model["model"],
                   "-c", 'model_provider="fixture"', "-c", 'model_providers.fixture.name="fixture"',
                   "-c", f'model_providers.fixture.base_url="{url}/codex"',
                   "-c", 'model_providers.fixture.wire_api="responses"',
                   "-c", 'model_providers.fixture.env_key="OPENAI_API_KEY"',
                   "-c", 'model_providers.fixture.request_max_retries=0',
                   "-c", 'model_providers.fixture.stream_max_retries=0',
                   # a harmless hook the seat wrapper would also install: this is the screen
                   # Codex puts up when a hook it has not been trusted with is configured
                   *(["-c", 'hooks.SessionStart=[{hooks=[{type="command",command="true"}]}]']
                     if state == "dialog" else []), *ask]
        else:
            cmd = ["muse", "--yolo", "--model", model["model"],
                   "--base-url", url + "/muse", *ask]
        if harness == "muse" and state == "dialog":
            # Muse's own chooser, the one screen it puts up and waits on with no provider
            cmd = ["muse", "--yolo", "--model", model["model"], "--base-url", url + "/muse"]
            env.pop("META_API_KEY")
        # Clear inherited auth/config/session overrides before setting this capture's home.
        command = ["env", "-i", "PATH=" + os.environ["PATH"],
                   *[f"{key}={value}" for key, value in env.items()], *cmd]
        tm("new-session", "-d", "-s", harness, "-x", "100", "-y", "30", "-c", str(home),
           shlex.join(command) + "; sleep 605")
        name = f"{harness}-pane.txt" if not state else f"{harness}-{state}-pane.txt"
        marks = SETTLED.get((harness, state), ())
        last, tries = "", 600 if not state else 120
        for _ in range(tries):
            time.sleep(1)
            pane = tm("capture-pane", "-p", "-t", f"={harness}:")
            (out / name).write_text(pane)
            if "Do you want to use this API key?" in pane:
                tm("send-keys", "-t", f"={harness}:", "Up", "Enter")
                continue
            if state != "dialog":
                # answered only where the dialog is in the way; the `dialog` run wants it left up
                if "Do you trust the contents of this directory?" in pane:
                    tm("send-keys", "-t", f"={harness}:", "Enter")
                    continue
                if "Yes, I accept" in pane:
                    tm("send-keys", "-t", f"={harness}:", "Down", "Enter")
                    continue
            if marks:
                # a dialog stands still; a turn in flight repaints its own timer every second,
                # so only the dialog captures wait for the pane to stop changing
                found = any(mark.lower() in pane.lower() for mark in marks)
                if found and (state != "dialog" or pane == last):
                    break
            elif state == "prompt":
                # nothing is running: the composer has to have painted and then stood still
                if pane == last and pane.strip() and "esc to interrupt" not in pane.lower():
                    break
            elif pane == last and ("API Error" in pane or "rate limit" in pane or "429" in pane or
                                   (auth and any(word in pane for word in
                                                 ("/login", "401", "Not logged in")))):
                break
            last = pane
        else:
            raise SystemExit(f"{harness}: no stable {state or 'error'} screen; "
                             f"inspect {out / name}")
        print(f"captured {harness} {state or 'stall'}", flush=True)
finally:
    subprocess.run(["tmux", "-L", "agentkit-test", "-S", socket, "kill-server"],
                   stderr=subprocess.DEVNULL)
    server.shutdown()
    os.close(fd)
