#!/usr/bin/env python3
"""The shared desktop as an MCP server, and as a CLI for the harness that has no MCP.

The server on `:99` is the same X display the shared Chromium draws on, so this is how an
agent reaches everything the browser tools cannot: the window manager, a native file dialog,
a page that only answers to a real click.  Everything here is one `xdotool` call, or one
ImageMagick `import`, against that display -- there is no state of its own to get out of step
with what the screen actually shows.

Two front ends over one set of actions.  Claude Code and Codex speak MCP over stdio;
`--cli` is the same actions for muse, which has no MCP client, and for a shell check.

stdlib only, because it has to start under whatever interpreter the harness happens to hand
it, on a box where the bridge's venv may not be on the path.
"""

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DISPLAY = ":99"                                                    # the shared X display
XAUTHORITY = Path.home() / ".local/share/browser-bridge/Xauthority"
PROTOCOL = "2025-06-18"        # the version answered when the client names none we know
KNOWN = ("2024-11-05", "2025-03-26", "2025-06-18")
SERVER = {"name": "desktop", "version": "1.0.0"}
CALL_CAP = 30                  # no xdotool or import call here has any reason to outlive this
BUTTONS = {"left": 1, "middle": 2, "right": 3}
WHEEL = {"up": 4, "down": 5, "left": 6, "right": 7}
COMBO = re.compile(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*$")
DRAG_STEPS = 8                 # a press-jump-release is ignored by anything that tracks motion
_geometry = None


class Failure(Exception):
    """Something the caller can act on: reported as a tool error, never as a traceback."""


def environment():
    """The X environment these tools need, with the bridge's display as the default.

    An agent that already exported DISPLAY/XAUTHORITY (the MCP registrations do) keeps them;
    a bare shell gets the shared desktop, which is the only one on this machine anyway.
    """
    env = dict(os.environ)
    if not env.get("DISPLAY"):
        env["DISPLAY"] = DISPLAY
    if not env.get("XAUTHORITY") and XAUTHORITY.exists():
        env["XAUTHORITY"] = str(XAUTHORITY)
    return env


def run(cmd):
    """Run one X tool and return its raw stdout; anything but a clean exit is a Failure."""
    tool = shutil.which(cmd[0])
    if tool is None:
        raise Failure(f"{cmd[0]} is not installed on this machine; `ak browser install` adds it")
    try:
        proc = subprocess.run([tool, *cmd[1:]], env=environment(), timeout=CALL_CAP,
                              stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        raise Failure(f"{cmd[0]} did not return within {CALL_CAP}s") from None
    except OSError as exc:
        raise Failure(f"cannot run {cmd[0]}: {exc}") from None
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or "no output"
        raise Failure(f"{cmd[0]} exited {proc.returncode}: {detail}")
    return proc.stdout


def geometry():
    """(width, height) of the shared display, read once and kept for the process's life.

    Xvfb is started at a fixed size and never resized, so one read is the truth; it is here to
    turn an off-screen coordinate into a message instead of a click silently clamped to the
    edge, which reads as "the click did nothing".
    """
    global _geometry
    if _geometry is None:
        shell = run(["xdotool", "getdisplaygeometry", "--shell"]).decode("utf-8", "replace")
        found = dict(line.split("=", 1) for line in shell.split() if "=" in line)
        try:
            _geometry = int(found["WIDTH"]), int(found["HEIGHT"])
        except (KeyError, ValueError):
            raise Failure(f"xdotool did not report a display geometry: {shell.strip()!r}") from None
    return _geometry


def point(x, y):
    """Validate a coordinate pair against the real screen."""
    width, height = geometry()
    out = []
    for name, value in (("x", x), ("y", y)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise Failure(f"{name} must be a number, not {type(value).__name__}")
        out.append(int(value))
    if not (0 <= out[0] < width and 0 <= out[1] < height):
        raise Failure(f"({out[0]}, {out[1]}) is off the {width}x{height} screen")
    return out


def whole(name, value, low, high, default):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise Failure(f"{name} must be a whole number")
    if not low <= value <= high:
        raise Failure(f"{name} must be between {low} and {high}")
    return int(value)


def button(name):
    if name is None:
        return BUTTONS["left"]
    if name not in BUTTONS:
        raise Failure(f"button must be one of {', '.join(BUTTONS)}, not {name!r}")
    return BUTTONS[name]


# --- the actions ------------------------------------------------------------
# Each returns either a string (reported as text) or ("image/png", bytes).


def do_screenshot():
    """The whole root window, which on :99 is the browser and its window manager."""
    for cmd in (["import", "-window", "root", "png:-"],
                ["magick", "import", "-window", "root", "png:-"]):
        if shutil.which(cmd[0]):
            return "image/png", run(cmd)
    raise Failure("no ImageMagick `import` on this machine; `ak browser install` adds it")


def do_move(x=None, y=None):
    x, y = point(x, y)
    run(["xdotool", "mousemove", "--sync", str(x), str(y)])
    return f"moved to ({x}, {y})"


def do_click(x=None, y=None, button_name=None):
    x, y = point(x, y)
    code = button(button_name)
    run(["xdotool", "mousemove", "--sync", str(x), str(y), "click", str(code)])
    return f"{button_name or 'left'} click at ({x}, {y})"


def do_double_click(x=None, y=None, button_name=None):
    x, y = point(x, y)
    code = button(button_name)
    run(["xdotool", "mousemove", "--sync", str(x), str(y),
         "click", "--repeat", "2", "--delay", "80", str(code)])
    return f"double click at ({x}, {y})"


def do_drag(x=None, y=None, to_x=None, to_y=None, button_name=None):
    """Press, travel in steps, release: a jump from press to release is not a drag.

    Anything that follows pointer motion -- a slider, a selection, an HTML5 drag -- needs the
    intermediate positions; without them the press and the release look like two clicks.
    """
    x, y = point(x, y)
    to_x, to_y = point(to_x, to_y)
    code = button(button_name)
    cmd = ["xdotool", "mousemove", "--sync", str(x), str(y), "mousedown", str(code)]
    for step in range(1, DRAG_STEPS + 1):
        cmd += ["mousemove", "--sync",
                str(x + (to_x - x) * step // DRAG_STEPS),
                str(y + (to_y - y) * step // DRAG_STEPS)]
    cmd += ["mouseup", str(code)]
    run(cmd)
    return f"dragged ({x}, {y}) -> ({to_x}, {to_y})"


def do_type(text=None, delay=None):
    if not isinstance(text, str):
        raise Failure("text must be a string")
    if not text:
        raise Failure("text is empty")
    # `--` so a string starting with a dash is typed, not read as an option
    run(["xdotool", "type", "--clearmodifiers", "--delay",
         str(whole("delay", delay, 0, 500, 12)), "--", text])
    return f"typed {len(text)} character{'' if len(text) == 1 else 's'}"


def do_key(combo=None):
    """One X keysym combination, or several separated by spaces (`ctrl+l Return`)."""
    if not isinstance(combo, str) or not combo.strip():
        raise Failure("combo must be a non-empty string, such as 'ctrl+l' or 'Return'")
    keys = combo.split()
    for key in keys:
        if not COMBO.match(key):
            raise Failure(f"{key!r} is not an X keysym combination such as 'ctrl+shift+t'")
    run(["xdotool", "key", "--clearmodifiers", "--"] + keys)
    return f"pressed {' '.join(keys)}"


def do_scroll(x=None, y=None, direction=None, amount=None):
    x, y = point(x, y)
    if direction not in WHEEL:
        raise Failure(f"direction must be one of {', '.join(WHEEL)}, not {direction!r}")
    clicks = whole("amount", amount, 1, 25, 3)
    run(["xdotool", "mousemove", "--sync", str(x), str(y),
         "click", "--repeat", str(clicks), "--delay", "40", str(WHEEL[direction])])
    return f"scrolled {direction} {clicks} at ({x}, {y})"


def do_cursor_position():
    shell = run(["xdotool", "getmouselocation", "--shell"]).decode("utf-8", "replace")
    found = dict(line.split("=", 1) for line in shell.split() if "=" in line)
    try:
        return f"cursor at ({int(found['X'])}, {int(found['Y'])})"
    except (KeyError, ValueError):
        raise Failure(f"xdotool did not report a cursor position: {shell.strip()!r}") from None


def number(description):
    return {"type": "number", "description": description}


TOOLS = (
    {"name": "screenshot", "handler": do_screenshot,
     "description": "Take a PNG screenshot of the whole shared desktop on display :99.",
     "properties": {}, "required": [], "cli": ()},
    {"name": "click", "handler": do_click,
     "description": "Click once at a screen coordinate.",
     "properties": {"x": number("Pixels from the left edge"),
                    "y": number("Pixels from the top edge"),
                    "button": {"type": "string", "enum": list(BUTTONS),
                               "description": "Mouse button; left by default"}},
     "required": ["x", "y"], "cli": ("x", "y", "button")},
    {"name": "double_click", "handler": do_double_click,
     "description": "Double-click at a screen coordinate.",
     "properties": {"x": number("Pixels from the left edge"),
                    "y": number("Pixels from the top edge"),
                    "button": {"type": "string", "enum": list(BUTTONS),
                               "description": "Mouse button; left by default"}},
     "required": ["x", "y"], "cli": ("x", "y", "button")},
    {"name": "move", "handler": do_move,
     "description": "Move the pointer without pressing anything, to reveal a hover state.",
     "properties": {"x": number("Pixels from the left edge"),
                    "y": number("Pixels from the top edge")},
     "required": ["x", "y"], "cli": ("x", "y")},
    {"name": "drag", "handler": do_drag,
     "description": "Press at one coordinate, travel to another, release.",
     "properties": {"x": number("Where the drag starts, from the left edge"),
                    "y": number("Where the drag starts, from the top edge"),
                    "to_x": number("Where the drag ends, from the left edge"),
                    "to_y": number("Where the drag ends, from the top edge"),
                    "button": {"type": "string", "enum": list(BUTTONS),
                               "description": "Mouse button; left by default"}},
     "required": ["x", "y", "to_x", "to_y"], "cli": ("x", "y", "to_x", "to_y", "button")},
    {"name": "type", "handler": do_type,
     "description": "Type text into whatever holds the keyboard focus.",
     "properties": {"text": {"type": "string", "description": "The literal text to type"},
                    "delay": number("Milliseconds between keystrokes; 12 by default")},
     "required": ["text"], "cli": ("text", "delay")},
    {"name": "key", "handler": do_key,
     "description": "Press an X keysym combination, such as 'ctrl+l', 'Return', or "
                    "'ctrl+l Return' for a sequence.",
     "properties": {"combo": {"type": "string", "description": "One combination, or several "
                                                               "separated by spaces"}},
     "required": ["combo"], "cli": ("combo",)},
    {"name": "scroll", "handler": do_scroll,
     "description": "Scroll the wheel over a coordinate.",
     "properties": {"x": number("Pixels from the left edge"),
                    "y": number("Pixels from the top edge"),
                    "direction": {"type": "string", "enum": list(WHEEL),
                                  "description": "Which way to scroll"},
                    "amount": number("Wheel clicks, 1-25; 3 by default")},
     "required": ["x", "y", "direction"], "cli": ("x", "y", "direction", "amount")},
    {"name": "cursor_position", "handler": do_cursor_position,
     "description": "Report where the pointer currently is.",
     "properties": {}, "required": [], "cli": ()},
)
BY_NAME = {tool["name"]: tool for tool in TOOLS}
# `button` is the JSON name; the handlers take button_name, because `button()` validates it
ARGUMENT = {"button": "button_name"}


def invoke(tool, arguments):
    """Call one action with the JSON arguments, rejecting names it does not take."""
    if not isinstance(arguments, dict):
        raise Failure("arguments must be an object")
    unknown = sorted(set(arguments) - set(tool["properties"]))
    if unknown:
        raise Failure(f"{tool['name']} takes no argument named {', '.join(unknown)}")
    missing = [name for name in tool["required"] if arguments.get(name) is None]
    if missing:
        raise Failure(f"{tool['name']} needs {', '.join(missing)}")
    return tool["handler"](**{ARGUMENT.get(k, k): v for k, v in arguments.items()})


def content(result):
    """One action's return value as MCP content."""
    if isinstance(result, tuple):
        mime, raw = result
        return [{"type": "image", "mimeType": mime,
                 "data": base64.b64encode(raw).decode("ascii")}]
    return [{"type": "text", "text": result}]


# --- the MCP server ---------------------------------------------------------


def schema(tool):
    return {"name": tool["name"], "description": tool["description"],
            "inputSchema": {"type": "object", "properties": tool["properties"],
                            "required": tool["required"], "additionalProperties": False}}


def dispatch(method, params):
    """The result for one request, or a Failure/ValueError the caller turns into an error."""
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"protocolVersion": asked if asked in KNOWN else PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [schema(tool) for tool in TOOLS]}
    if method == "tools/call":
        name = params.get("name")
        tool = BY_NAME.get(name)
        if tool is None:
            raise ValueError(f"no tool named {name!r}; this server has "
                             f"{', '.join(BY_NAME)}")
        try:
            return {"content": content(invoke(tool, params.get("arguments") or {}))}
        except Failure as exc:
            # A bad coordinate or a missing xdotool is the model's to fix, so it comes back
            # as a tool result it can read, not as a protocol error that ends the call.
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    raise LookupError(method)


def serve(stdin, stdout):
    """One JSON-RPC message per line, until the harness closes the pipe."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError as exc:
            reply(stdout, {"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32700, "message": f"invalid JSON: {exc}"}})
            continue
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            reply(stdout, {"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32600, "message": "expected a JSON-RPC 2.0 object"}})
            continue
        ident, method = message.get("id"), message.get("method")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method is None:                      # a response to something we never sent
            continue
        try:
            result = dispatch(method, params)
        except LookupError:
            if ident is not None:               # notifications/initialized and friends
                reply(stdout, {"jsonrpc": "2.0", "id": ident,
                               "error": {"code": -32601,
                                         "message": f"unknown method {method!r}"}})
            continue
        except (Failure, ValueError) as exc:
            if ident is not None:
                reply(stdout, {"jsonrpc": "2.0", "id": ident,
                               "error": {"code": -32602, "message": str(exc)}})
            continue
        if ident is not None:
            reply(stdout, {"jsonrpc": "2.0", "id": ident, "result": result})


def reply(stdout, message):
    stdout.write(json.dumps(message) + "\n")
    stdout.flush()


# --- the CLI ----------------------------------------------------------------


def cli(argv):
    """`--cli <action> [args...]`, positional in the order the tool lists them.

    `screenshot` takes the file to write; the rest print one line.  This is muse's path to the
    desktop, and the one a done-when command can call.
    """
    if not argv:
        raise Failure("--cli needs an action: screenshot, " + ", ".join(
            name for name in BY_NAME if name != "screenshot"))
    name, rest = argv[0], argv[1:]
    tool = BY_NAME.get(name)
    if tool is None:
        raise Failure(f"no action named {name!r}; this CLI has {', '.join(BY_NAME)}")
    if name == "screenshot":
        if len(rest) != 1:
            raise Failure("--cli screenshot needs one argument: the PNG file to write")
        _, raw = do_screenshot()
        path = Path(rest[0]).expanduser()
        try:
            path.write_bytes(raw)
        except OSError as exc:
            raise Failure(f"cannot write {path}: {exc}") from None
        print(path)
        return 0
    if len(rest) > len(tool["cli"]):
        raise Failure(f"--cli {name} takes at most {len(tool['cli'])} argument(s): "
                      + " ".join(tool["cli"]))
    arguments = {}
    for key, value in zip(tool["cli"], rest):
        if tool["properties"][key]["type"] == "number":
            try:
                value = float(value) if "." in value else int(value)
            except ValueError:
                raise Failure(f"{key} must be a number, not {value!r}") from None
        arguments[key] = value
    print(invoke(tool, arguments))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="The shared desktop on :99, as an MCP server over stdio or as a CLI.")
    parser.add_argument("--cli", action="store_true",
                        help="run one action and exit, instead of serving MCP")
    parser.add_argument("action", nargs=argparse.REMAINDER,
                        help="with --cli: the action and its positional arguments")
    args = parser.parse_args(argv)
    if not args.cli:
        if args.action:
            parser.error("actions are only for --cli; without it this serves MCP on stdio")
        serve(sys.stdin, sys.stdout)
        return 0
    try:
        return cli(args.action)
    except Failure as exc:
        print(f"desktop: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        sys.exit(0)
