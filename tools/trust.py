#!/usr/bin/env python3
"""Mark a directory as trusted for a harness before its TUI starts, so a new orchestrator session
lands in the prompt instead of a "do you trust this folder?" dialog. Usage: trust.py <claude|codex> <dir>"""
import json, os, sys, pathlib

def claude(d):
    p = pathlib.Path.home() / ".claude.json"
    data = json.loads(p.read_text()) if p.exists() else {}
    proj = data.setdefault("projects", {}).setdefault(d, {})
    changed = not proj.get("hasTrustDialogAccepted") or not data.get("theme") or not data.get("hasCompletedOnboarding")
    proj["hasTrustDialogAccepted"] = True
    data.setdefault("theme", "dark"); data["hasCompletedOnboarding"] = True
    if changed:
        tmp = p.with_suffix(".json.tmp"); tmp.write_text(json.dumps(data, indent=2)); os.replace(tmp, p)

def codex(d):
    p = pathlib.Path.home() / ".codex" / "config.toml"
    text = p.read_text() if p.exists() else ""
    header = f'[projects."{d}"]'
    if header not in text:
        with p.open("a") as f:
            f.write(f'\n{header}\ntrust_level = "trusted"\n')

if __name__ == "__main__":
    # trust.py <claude|codex> -- <command...>   trusts the current directory, then execs the command
    # trust.py <claude|codex> <dir>             trusts <dir> and exits
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] in ("claude", "codex") and a[1] == "--":
        {"claude": claude, "codex": codex}[a[0]](os.path.realpath(os.getcwd()))
        os.execvp(a[2], a[2:])
    if len(a) != 2 or a[0] not in ("claude", "codex"):
        print(__doc__, file=sys.stderr); sys.exit(2)
    {"claude": claude, "codex": codex}[a[0]](os.path.realpath(a[1]))
