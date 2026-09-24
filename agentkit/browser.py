"""`ak browser`: the server's one shared, logged-in Chromium, and the desktop it draws on.

The stack itself predates this module and is not run by it: five system units hold an Xvfb
display `:99`, a window manager, a Chromium whose profile carries the owner's real logins, an
x11vnc on loopback and a noVNC that listens only on the Tailscale address.  What was missing
was a way in.  This is it, and it is deliberately thin:

  status         is everything down there reachable, and how many tabs are open
  login          the URL and password the owner needs to sign a site in, by hand, once
  mcp-register   point Claude Code and Codex at that browser and at that desktop
  install        stand the stack up on a machine that has none; verify on the one that has

Nothing here restarts Chromium.  Its profile is the logins: a restart costs whatever a site
had not yet flushed, and a re-login the owner has to sit through.  `login` restarts x11vnc and
only x11vnc, and only when it had to mint a new password.

The browser reaches the harnesses over CDP, not through the Chrome extensions: `@playwright/mcp
--cdp-endpoint` without `--isolated` attaches to the profile's own default context, which is
where the cookies are.  The desktop reaches them through `tools/desktop-mcp.py`, whose xdotool
calls land on the same `:99`.
"""

import ctypes
import ctypes.util
import json
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from . import command_help, config

BRIDGE = Path.home() / ".local/share/browser-bridge"     # the stack's own directory
PAYLOAD = config.REPO / "browser"                        # its copy in here, for a fresh machine
DESKTOP = config.REPO / "tools" / "desktop-mcp.py"
DISPLAY = ":99"
CDP = "http://127.0.0.1:9222"
UNITS = tuple(f"browser-bridge-{part}.service"
              for part in ("xvfb", "openbox", "chromium", "x11vnc", "novnc"))
UNIT_DIR = Path("/etc/systemd/system")
PACKAGES = ("chromium", "xvfb", "openbox", "x11vnc", "novnc", "websockify",
            "xdotool", "imagemagick")
PAYLOAD_FILES = ("bridge.py", "install.sh", "prepare-profile.py", "wait-ready.py",
                 "stop-chromium.py", "requirements.txt")
SECRET = config.SECRETS / "browser-bridge-vnc.txt"       # the password as text, for the owner
LEGACY = config.SECRETS / "browser-bridge-vnc"           # what the stack's installer wrote
RFBAUTH = config.SECRETS / "browser-bridge-vnc.rfbauth"  # the same password, as x11vnc wants it
PASSWORD_LENGTH = 16          # noVNC takes all of it; classic VNC auth uses the first eight
CDP_TIMEOUT = 4
APT_CAP = 15 * 60
NPX_CAP = 5 * 60              # a cold `npx -y` fetches the package before it prints anything

CLAUDE_CONFIG = Path.home() / ".claude.json"             # user scope lives at the top level
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
BEGIN = "# --- agentkit browser bridge: managed by `ak browser mcp-register` ---"
END = "# --- end agentkit browser bridge ---"
HOST_PORT = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}|\[[0-9A-Fa-f:]+\]):(\d{1,5})$")

USAGE = command_help.render("browser").rstrip()


def say(message):
    print(message, flush=True)


def servers():
    """The two MCP servers, as {name: (command, args, env)}.

    `--isolated` is deliberately absent: with it Playwright opens a fresh context and the
    profile's cookies are not in it, which is the whole point of attaching to this browser.
    """
    return {
        "browser": ("npx", ["-y", "@playwright/mcp@latest", "--cdp-endpoint", CDP]),
        "desktop": (sys.executable, [str(DESKTOP)]),
    }


def mcp_env():
    return {"DISPLAY": DISPLAY, "XAUTHORITY": str(BRIDGE / "Xauthority")}


# --- reading the running stack ---------------------------------------------


def systemctl(args, sudo=False, cap=120):
    """Run systemctl and return (returncode, stdout); (None, "") where there is none."""
    if shutil.which("systemctl") is None:
        return None, ""
    cmd = (["sudo", "-n"] if sudo else []) + ["systemctl"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                              timeout=cap, env=config.child_env())
    except subprocess.TimeoutExpired:
        raise config.Error(f"systemctl {' '.join(args)} did not return within {cap}s") from None
    except OSError as exc:
        raise config.Error(f"cannot run systemctl: {exc}") from None
    if sudo and proc.returncode != 0 and "password" in (proc.stderr or "").lower():
        raise config.Error("sudo asked for a password; this needs passwordless sudo")
    return proc.returncode, proc.stdout


def unit_states():
    """{unit: "active (running)" | "inactive (dead)" | "absent"}, or None off systemd."""
    code, out = systemctl(["show", "--no-pager",
                           "--property=Id", "--property=LoadState",
                           "--property=ActiveState", "--property=SubState", *UNITS])
    if code is None:
        return None
    blocks, current = {}, {}
    for line in out.splitlines() + [""]:
        if not line.strip():
            if current.get("Id"):
                blocks[current["Id"]] = current
            current = {}
            continue
        key, _, value = line.partition("=")
        current[key] = value
    states = {}
    for unit in UNITS:
        block = blocks.get(unit)
        if block is None or block.get("LoadState") in (None, "not-found", "masked"):
            states[unit] = "absent"
        else:
            states[unit] = f"{block.get('ActiveState', '?')} ({block.get('SubState', '?')})"
    return states


def cdp(path):
    """One CDP HTTP read.  Raises OSError/ValueError when the browser is not there."""
    with urllib.request.urlopen(CDP + path, timeout=CDP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def tabs():
    """The open pages, newest CDP order, excluding iframes and browser chrome."""
    return [target for target in cdp("/json/list") if target.get("type") == "page"]


def tab_idle_minutes():
    """Minutes a tab may go unused before the watch tick closes it."""
    try:
        value = int(os.environ.get("AK_BROWSER_TAB_IDLE_MIN", 60))
    except (TypeError, ValueError):
        return 60
    return value if value > 0 else 60


def tab_cap():
    """How many open tabs the watch tick tolerates before closing the oldest."""
    try:
        value = int(os.environ.get("AK_BROWSER_TAB_CAP", 12))
    except (TypeError, ValueError):
        return 12
    return value if value >= 1 else 12


def tab_records_path():
    return config.STATE / "browser-tabs.json"


def idle_word(seconds):
    """`idle 12m` / `idle 3h` for a tab unused that long."""
    if seconds >= 3600:
        return f"idle {int(seconds // 3600)}h"
    return f"idle {int(seconds // 60)}m"


def close_tab(target_id):
    """Close one tab through CDP's HTTP endpoint.  Raises when it does not close."""
    with urllib.request.urlopen(CDP + "/json/close/" + target_id,
                               timeout=CDP_TIMEOUT) as response:
        response.read()


def _write_tabs(stored):
    config.ensure_dirs()
    tmp = tab_records_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
    tmp.replace(tab_records_path())


def _read_tabs():
    try:
        stored = json.loads(tab_records_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def note_opener(target_id, *, run=None, session=None):
    """Remember who opened a tab, so it can be closed when that run or seat ends.

    A tab with no recorded opener is left to the idle rule. Either name may be set;
    a run's tab also names its seat when the opener knew both.
    """
    if not isinstance(target_id, str) or not target_id or (not run and not session):
        return
    opener = {}
    if isinstance(run, str) and run:
        opener["run"] = run
    if isinstance(session, str) and session:
        opener["session"] = session
    if not opener:
        return
    stored = _read_tabs()
    record = stored.get(target_id)
    if not isinstance(record, dict):
        now = time.time()
        record = {"first_seen": now, "last_change": now, "url": "", "title": ""}
    previous = record.get("opener") if isinstance(record.get("opener"), dict) else {}
    record["opener"] = {**previous, **opener}
    stored[target_id] = record
    try:
        _write_tabs(stored)
    except (OSError, ValueError):
        return


def _owned(record, *, run=None, session=None, runs=()):
    """Whether this record's opener is the run or the seat being closed.

    No opener, or an opener we cannot read, is not owned: the idle rule decides it.
    """
    opener = record.get("opener") if isinstance(record, dict) else None
    if not isinstance(opener, dict):
        return False
    owned_runs = {item for item in runs if isinstance(item, str) and item}
    if isinstance(run, str) and run:
        owned_runs.add(run)
    if opener.get("run") in owned_runs:
        return True
    return bool(session) and opener.get("session") == session


def close_owned(*, run=None, session=None, runs=()):
    """Close tabs this run or seat opened. Tabs with no recorded opener stay put.

    Best effort, and it never calls CDP when nothing in the record matches: a stop
    must not depend on the browser being up. Returns the ids that actually closed.
    """
    stored = _read_tabs()
    victims = [target_id for target_id, record in stored.items()
               if isinstance(target_id, str)
               and _owned(record, run=run, session=session, runs=runs)]
    if not victims:
        return []
    closed = []
    for target_id in victims:
        try:
            close_tab(target_id)
        except Exception:
            continue
        closed.append(target_id)
    if not closed:
        return []
    remaining = {target_id: record for target_id, record in stored.items()
                 if target_id not in closed}
    try:
        _write_tabs(remaining)
    except (OSError, ValueError):
        return closed
    return closed


def tidy(log, now=None):
    """Close the tabs nobody has used, once per watch tick.  Never the browser.

    A tab whose url and title have not changed for AK_BROWSER_TAB_IDLE_MIN minutes
    (default 60) is closed, unless it is the most recently changed tab; past
    AK_BROWSER_TAB_CAP open tabs (default 12) the oldest by last change go too.
    The last remaining tab never closes, and frames and workers are never touched.
    Best effort: an unreachable or malformed CDP answer costs nothing, a failed
    close is skipped, and at most the one closing line is logged.
    """
    try:
        _tidy(log, time.time() if now is None else now)
    except Exception:
        return


def _tidy(log, now):
    current = tabs()
    if not isinstance(current, list):
        return
    pages = []
    for target in current:
        if not isinstance(target, dict) or not isinstance(target.get("id"), str):
            return
        pages.append(target)
    stored = _read_tabs()
    updated = {}
    for target in pages:
        target_id = target["id"]
        url = target.get("url") if isinstance(target.get("url"), str) else ""
        title = target.get("title") if isinstance(target.get("title"), str) else ""
        old = stored.get(target_id)
        if (isinstance(old, dict) and old.get("url") == url and old.get("title") == title
                and isinstance(old.get("last_change"), (int, float))
                and not isinstance(old.get("last_change"), bool)):
            updated[target_id] = old
        else:
            first = old.get("first_seen") if isinstance(old, dict) else None
            if not isinstance(first, (int, float)) or isinstance(first, bool):
                first = now
            record = {"first_seen": first, "last_change": now, "url": url, "title": title}
            # The idle clock resets when the page changes; who opened it does not.
            if isinstance(old, dict) and isinstance(old.get("opener"), dict):
                record["opener"] = old["opener"]
            updated[target_id] = record
    # tabs() is newest CDP order, so on equal last_change the earlier list entry is the
    # more recently used one; the cap rule then never spends a live tab on a coin toss.
    order = {target["id"]: index for index, target in enumerate(pages)}
    victims = set()
    if len(pages) > 1:
        newest = max(updated,
                     key=lambda tid: (updated[tid]["last_change"], -order[tid]))
        idle_for = tab_idle_minutes() * 60
        for target_id, record in updated.items():
            if target_id != newest and now - record["last_change"] >= idle_for:
                victims.add(target_id)
        if len(pages) > tab_cap():
            oldest = sorted(updated,
                            key=lambda tid: (updated[tid]["last_change"], -order[tid]))
            for target_id in oldest[:len(pages) - tab_cap()]:
                victims.add(target_id)
        if len(victims) >= len(pages):
            victims.discard(newest)
    closed = []
    for target_id in sorted(victims,
                            key=lambda tid: (updated[tid]["last_change"], -order[tid])):
        try:
            close_tab(target_id)
        except Exception:
            continue
        closed.append(target_id)
    if closed:
        names = [((updated[target_id].get("title") or "").strip() or "(untitled)")[:40]
                 for target_id in closed[:3]]
        log(f"browser: closed {len(closed)} idle tabs ({len(pages)} → {len(pages) - len(closed)}): "
            f"{', '.join(names)}")
    remaining = {target_id: record for target_id, record in updated.items()
                 if target_id not in closed}
    try:
        _write_tabs(remaining)
    except (OSError, ValueError):
        return


def novnc_url():
    """The address websockify was told to listen on, read from the unit that runs it.

    Taken from the unit rather than hard-coded, so a machine whose Tailscale address differs
    still prints a URL that works.  The 127.0.0.1:5900 in the same line is the VNC it proxies.
    """
    for path in (UNIT_DIR / "browser-bridge-novnc.service",
                 PAYLOAD / "systemd" / "browser-bridge-novnc.service"):
        try:
            text = path.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            if not line.startswith("ExecStart="):
                continue
            for token in line.split():
                found = HOST_PORT.match(token)
                if found and token != "127.0.0.1:5900":
                    return f"http://{token}/vnc.html?autoconnect=1&resize=remote"
    return None


def desktop_tools():
    """Which of the desktop's two outside dependencies are on this machine."""
    have_import = shutil.which("import") or shutil.which("magick")
    return shutil.which("xdotool"), have_import


# --- status -----------------------------------------------------------------


def status(argv):
    if argv:
        raise config.Error(f"ak browser status takes no arguments; got {' '.join(argv)}")
    healthy, states = True, unit_states()
    if states is None:
        say("units      no systemd on this machine; the stack lives on the server")
    else:
        for unit, state in states.items():
            say(f"  {unit:<32} {state}")
        if all(state == "absent" for state in states.values()):
            say("units      none installed here; `ak browser install` puts them in")
        elif any(not state.startswith("active") for state in states.values()):
            healthy = False
    try:
        version = cdp("/json/version")
        open_tabs = tabs()
    except (OSError, ValueError, urllib.error.URLError) as exc:
        reason = getattr(exc, "reason", exc)
        say(f"cdp        {CDP} unreachable ({reason})")
        # Not a failure where nothing is installed: that is a Mac, and it never had a browser.
        if states and any(state != "absent" for state in states.values()):
            healthy = False
    else:
        say(f"cdp        {CDP} reachable, {version.get('Browser', 'unknown build')}")
        say(f"tabs       {len(open_tabs)} open (cap {tab_cap()}; a tab idle "
            f"{tab_idle_minutes()} min is closed by ak watch)")
        try:
            stored = json.loads(tab_records_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        moment = time.time()
        for target in open_tabs:
            title = (target.get("title") or "").strip() or "(untitled)"
            record = stored.get(target.get("id"))
            changed = record.get("last_change") if isinstance(record, dict) else None
            if not isinstance(changed, (int, float)) or isinstance(changed, bool) \
                    or changed > moment:
                changed = moment
            say(f"  {title[:60]:<60} {target.get('url', '')[:80]} {idle_word(moment - changed)}")
    xdotool, imagemagick = desktop_tools()
    missing = [name for name, found in (("xdotool", xdotool), ("imagemagick", imagemagick))
               if not found]
    say(f"desktop    DISPLAY={DISPLAY}"
        + (f", missing {', '.join(missing)}" if missing else ", xdotool and import present"))
    url = novnc_url()
    say(f"novnc      {url}" if url else
        "novnc      no address recorded; the noVNC unit is not installed here")
    return 0 if healthy else 1


# --- login ------------------------------------------------------------------


def plaintext():
    """The VNC password as text, from either name the stack has used, or None."""
    for path in (SECRET, LEGACY):
        try:
            found = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if found:
            return found
    return None


def store_rfbauth(password):
    """Write x11vnc's authentication file the way the stack's own installer does.

    Through libvncserver, not `x11vnc -storepasswd`, because that one takes the password as a
    command-line argument, where every process on the box can read it.
    """
    library = ctypes.util.find_library("vncserver")
    if library is None:
        raise config.Error("libvncserver is not on this machine, so the x11vnc password file "
                           "cannot be written; install x11vnc first")
    store = ctypes.CDLL(library).rfbEncryptAndStorePasswd
    store.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    store.restype = ctypes.c_int
    # `.rfbauth.tmp`, not `.with_suffix`, which would drop the suffix and land on the
    # name `mint` uses for the plaintext a line earlier.
    temp = RFBAUTH.with_name(RFBAUTH.name + ".tmp")
    try:
        if store(password.encode(), os.fsencode(temp)) != 0:
            raise config.Error("libvncserver would not write the x11vnc password file")
        temp.chmod(0o600)
        temp.replace(RFBAUTH)
    finally:
        temp.unlink(missing_ok=True)


def mint():
    """A new password, in both forms, with x11vnc restarted onto it.

    Only reached when the plaintext is gone: either the rfbauth file is all that survived, and
    nobody can read a password out of it, or this is a machine with neither.
    """
    password = "".join(secrets.choice(string.ascii_letters + string.digits)
                       for _ in range(PASSWORD_LENGTH))
    config.ensure_dirs()
    temp = SECRET.with_name(SECRET.name + ".tmp")
    temp.write_text(password + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(SECRET)
    store_rfbauth(password)
    states = unit_states() or {}
    if states.get("browser-bridge-x11vnc.service", "absent") != "absent":
        code, _ = systemctl(["restart", "browser-bridge-x11vnc.service"], sudo=True)
        if code != 0:
            raise config.Error("wrote a new VNC password but could not restart "
                               "browser-bridge-x11vnc.service; the old password is still live")
        say("x11vnc restarted onto a new password; Chromium and its tabs were not touched")
    return password


def login(argv):
    if argv:
        raise config.Error(f"ak browser login takes no arguments; got {' '.join(argv)}")
    url = novnc_url()
    if url is None:
        raise config.Error("no noVNC address on this machine; run `ak browser install` on the "
                           "server, or read it there with `ak browser status`")
    password = plaintext()
    if password is None:
        if RFBAUTH.exists():
            say(f"{RFBAUTH.name} is here but the plaintext is not, and it cannot be read back "
                "out; minting a new password")
        password = mint()
    say(f"open      {url}")
    say(f"password  {password}")
    say("Sign the site in inside that window, finishing any 2FA or bot check yourself.  The "
        "session stays in the shared profile and every agent then sees it.  Only Tailscale "
        "reaches this address.")
    return 0


# --- mcp-register -----------------------------------------------------------


def write_atomic(path, text, mode=0o600):
    """Replace a config file without ever leaving a half-written one behind."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        mode = path.stat().st_mode & 0o777
    temp = path.with_name(path.name + ".ak-tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        temp.chmod(mode)
        temp.replace(path)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise config.Error(f"cannot write {path}: {exc}") from None


def register_claude():
    """Put both servers into ~/.claude.json's top-level mcpServers, user scope, in place."""
    data = {}
    if CLAUDE_CONFIG.exists():
        try:
            data = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8"))
        except OSError as exc:
            raise config.Error(f"cannot read {CLAUDE_CONFIG}: {exc}") from None
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise config.Error(f"{CLAUDE_CONFIG}: {exc}") from None
        if not isinstance(data, dict):
            raise config.Error(f"{CLAUDE_CONFIG}: expected a JSON object")
    existing = data.get("mcpServers")
    if existing is not None and not isinstance(existing, dict):
        raise config.Error(f"{CLAUDE_CONFIG}: mcpServers is not an object")
    wanted = {name: {"type": "stdio", "command": command, "args": args, "env": mcp_env()}
              for name, (command, args) in servers().items()}
    merged = {**(existing or {}), **wanted}
    if existing == merged:
        return "already registered"
    data["mcpServers"] = merged
    write_atomic(CLAUDE_CONFIG, json.dumps(data, indent=2) + "\n")
    return "registered"


def toml_string(value):
    """A TOML basic string.  Our values are paths and flags, which JSON escapes the same way."""
    return json.dumps(value)


def codex_block():
    lines = [BEGIN]
    for name, (command, args) in servers().items():
        env = ", ".join(f"{key} = {toml_string(value)}"
                        for key, value in sorted(mcp_env().items()))
        lines += [f"[mcp_servers.{name}]",
                  f"command = {toml_string(command)}",
                  "args = [" + ", ".join(toml_string(arg) for arg in args) + "]",
                  "env = { " + env + " }",
                  ""]
    lines.append(END)
    return "\n".join(lines) + "\n"


def register_codex():
    """Keep both servers in one marked block of ~/.codex/config.toml, and nothing else.

    A block, not a rewrite: install.sh and codex itself both own keys in this file, and a
    round trip through a TOML writer would lose their comments and their ordering.  A
    `[mcp_servers.browser]` somebody wrote by hand outside the block is an error rather than a
    second one appended, because two tables of the same name do not parse at all.
    """
    raw = ""
    if CODEX_CONFIG.exists():
        try:
            raw = CODEX_CONFIG.read_text(encoding="utf-8")
        except OSError as exc:
            raise config.Error(f"cannot read {CODEX_CONFIG}: {exc}") from None
        try:
            tomllib.loads(raw)
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            raise config.Error(f"{CODEX_CONFIG} is not valid TOML, so nothing was changed: {exc}")
    block = codex_block()
    start, stop = raw.find(BEGIN), raw.find(END)
    if start != -1 and stop > start:
        head, tail = raw[:start], raw[stop + len(END):].lstrip("\n")
        text = head + block + ("\n" + tail if tail else "")
    elif start != -1 or stop != -1:
        raise config.Error(f"{CODEX_CONFIG} has half of the agentkit block; repair or delete "
                           f"the lines between {BEGIN!r} and {END!r} and run this again")
    else:
        parsed = tomllib.loads(raw) if raw else {}
        clash = sorted(set(parsed.get("mcp_servers", {})) & set(servers()))
        if clash:
            raise config.Error(f"{CODEX_CONFIG} already defines mcp_servers."
                               f"{', mcp_servers.'.join(clash)} outside the agentkit block; "
                               "remove those tables and run this again")
        text = (raw.rstrip("\n") + "\n\n" if raw.strip() else "") + block
    try:
        result = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:      # a bug here, caught before it lands on disk
        raise config.Error(f"the block this would write does not parse: {exc}")
    if set(result.get("mcp_servers", {})) < set(servers()):
        raise config.Error(f"{CODEX_CONFIG}: the block did not take effect")
    if text == raw:
        return "already registered"
    write_atomic(CODEX_CONFIG, text)
    return "registered"


def warm_npx():
    """Fetch @playwright/mcp once, so the first MCP handshake is not a package download.

    Codex and Claude Code both give a stdio server a bounded time to answer `initialize`; a
    cold `npx -y` spends that time in the registry.  Best effort: a failure here costs a
    slower first call, not a broken registration.  Skipped where there is no browser to talk
    to, so registering on a client machine stays an offline, local edit.
    """
    try:
        cdp("/json/version")
    except (OSError, ValueError, urllib.error.URLError):
        return f"not warmed: no browser at {CDP} on this machine"
    if shutil.which("npx") is None:
        return "npx is not installed here; the browser server needs it"
    _, args = servers()["browser"]
    try:
        proc = subprocess.run(["npx", *args[:2], "--version"], capture_output=True,
                              encoding="utf-8", errors="replace", timeout=NPX_CAP,
                              env=config.child_env())
    except (OSError, subprocess.TimeoutExpired):
        return "could not warm the npx cache; the first browser call may be slow"
    return ("@playwright/mcp cached" if proc.returncode == 0 else
            "could not warm the npx cache; the first browser call may be slow")


def mcp_register(argv):
    if argv:
        raise config.Error(f"ak browser mcp-register takes no arguments; got {' '.join(argv)}")
    if not DESKTOP.exists():
        raise config.Error(f"{DESKTOP} is missing; this checkout is incomplete")
    say(f"claude    {register_claude()} in {CLAUDE_CONFIG} (user scope)")
    say(f"codex     {register_codex()} in {CODEX_CONFIG}")
    say(f"npx       {warm_npx()}")
    say("muse      has no MCP client: use browser/bridge.py and tools/desktop-mcp.py --cli")
    return 0


# --- install ----------------------------------------------------------------


def vendor():
    """Take the running stack's files into the repo, once, so a fresh machine can be rebuilt.

    Only ever a copy inwards: the machine that has the stack is the source of truth for it,
    and a file already committed here is never overwritten from a box that may have drifted.
    """
    have = [name for name in PAYLOAD_FILES if (PAYLOAD / name).exists()]
    units = list((PAYLOAD / "systemd").glob("*.service")) if (PAYLOAD / "systemd").is_dir() else []
    if len(have) == len(PAYLOAD_FILES) and len(units) == len(UNITS):
        return f"already in {PAYLOAD.relative_to(config.REPO)}/"
    if not BRIDGE.is_dir():
        return f"incomplete in {PAYLOAD.relative_to(config.REPO)}/ and no stack here to copy from"
    copied = []
    (PAYLOAD / "systemd").mkdir(mode=0o755, parents=True, exist_ok=True)
    for source, target in ([(BRIDGE / n, PAYLOAD / n) for n in PAYLOAD_FILES]
                           + [(BRIDGE / "systemd" / u, PAYLOAD / "systemd" / u) for u in UNITS]):
        if target.exists() or not source.exists():
            continue
        try:
            shutil.copyfile(source, target)
            target.chmod(0o755 if target.suffix == ".sh" or target.name == "bridge.py" else 0o644)
        except OSError as exc:
            raise config.Error(f"cannot copy {source} into the repo: {exc}") from None
        copied.append(target.name)
    return f"copied {len(copied)} file(s) into {PAYLOAD.relative_to(config.REPO)}/" if copied \
        else f"incomplete in {PAYLOAD.relative_to(config.REPO)}/ and the stack has no more to give"


def missing_packages():
    """The apt packages that are not installed, or None where there is no dpkg."""
    if shutil.which("dpkg-query") is None:
        return None
    missing = []
    for package in PACKAGES:
        try:
            proc = subprocess.run(["dpkg-query", "-W", "-f=${Status}", package],
                                  capture_output=True, encoding="utf-8", errors="replace",
                                  timeout=60, env=config.child_env())
        except (OSError, subprocess.TimeoutExpired):
            raise config.Error(f"cannot ask dpkg about {package}") from None
        if "install ok installed" not in proc.stdout:
            missing.append(package)
    return missing


def apt_install(packages):
    for cmd in (["sudo", "-n", "apt-get", "update"],
                ["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install",
                 "-y", "--no-install-recommends", *packages]):
        try:
            proc = subprocess.run(cmd, timeout=APT_CAP, env=config.child_env())
        except subprocess.TimeoutExpired:
            raise config.Error(f"{' '.join(cmd[:4])} did not finish within {APT_CAP}s") from None
        except OSError as exc:
            raise config.Error(f"cannot run apt-get: {exc}") from None
        if proc.returncode != 0:
            raise config.Error(f"{' '.join(cmd[:5])} exited {proc.returncode}")


def install(argv):
    """Stand the stack up where there is none; on the machine that has it, verify and stop.

    The stack's own installer restarts all five units at the end, which is exactly what must
    not happen to a Chromium holding live sessions.  So it is run only when the units are not
    there at all, and the machine that already has them gets the package check and nothing more.
    """
    if argv:
        raise config.Error(f"ak browser install takes no arguments; got {' '.join(argv)}")
    say(f"payload   {vendor()}")
    missing = missing_packages()
    if missing is None:
        say("packages  no dpkg on this machine; the stack is Debian-only")
    elif missing:
        say(f"packages  installing {', '.join(missing)}")
        apt_install(missing)
        still = missing_packages()
        if still:
            raise config.Error(f"apt-get reported success but {', '.join(still)} is still missing")
        say(f"packages  installed {', '.join(missing)}")
    else:
        say(f"packages  all {len(PACKAGES)} present")
    states = unit_states()
    if states is None:
        say("units     no systemd on this machine; nothing to install")
        return 0
    if all(state == "absent" for state in states.values()):
        installer = PAYLOAD / "install.sh"
        if not installer.exists():
            raise config.Error(f"{installer} is missing, so the stack cannot be built here")
        say(f"units     none installed; running {installer.relative_to(config.REPO)}")
        try:
            proc = subprocess.run(["bash", str(installer)], cwd=str(PAYLOAD), timeout=APT_CAP,
                                  env=config.child_env())
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise config.Error(f"{installer} did not finish: {exc}") from None
        if proc.returncode != 0:
            raise config.Error(f"{installer} exited {proc.returncode}")
        states = unit_states() or {}
    down = [unit for unit, state in states.items() if not state.startswith("active")]
    if down:
        say(f"units     not running: {', '.join(down)}; `ak browser status` has the detail")
        return 1
    say(f"units     all {len(UNITS)} active; the running browser was not touched")
    return 0


COMMANDS = {"status": status, "login": login, "mcp-register": mcp_register, "install": install}


def main(argv):
    if command_help.show("browser", argv):
        return 0
    if not argv:
        print(USAGE)
        return 2
    command = COMMANDS.get(argv[0])
    if command is None:
        print(f"ak browser: unknown command {argv[0]!r}; expected one of "
              f"{', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    try:
        return command(argv[1:])
    except BrokenPipeError:
        # `ak browser status | head` closes the pipe mid-print.  Left alone Python answers a
        # perfectly ordinary shell pipeline with a traceback, and then a second complaint when
        # it flushes stdout at shutdown; devnull takes both.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
