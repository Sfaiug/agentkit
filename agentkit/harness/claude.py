"""Claude Code: a launcher-issued conversation, and the transcript it writes for it.

An alternate login also needs the seat's trust and hooks in its own config directory.
"""

from pathlib import Path
import json
import os
import re
import sys


def opened(cwd, conversation):
    """Has Claude Code written that conversation down yet, where it keeps them?

    Its directory per workspace: every character that is not a letter or a digit becomes a
    dash, and each transcript is named for the session it holds.  Claude Code writes the
    transcript at the first message and not at the prompt, so a seat nobody typed into has
    nothing to resume, and `--resume` on it is an error rather than a conversation.
    """
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    return (Path.home() / ".claude" / "projects" / slug / f"{conversation}.jsonl").exists()


def account_config():
    """Keep an alternate login's settings, adding the trust and hooks every seat needs.

    Claude's config override moves both its user settings and its global .claude.json.
    Only trust and hooks are shared; the account's identity and credentials stay its own.
    """
    account = os.environ.get("AGENTKIT_ACCOUNT")
    if not account:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        return
    home = Path.home()
    directory = home / f".claude-{account}"
    directory.mkdir(parents=True, exist_ok=True)
    settings = home / ".claude/settings.json"
    hooks = json.loads(settings.read_text()).get("hooks", {}) if settings.exists() else {}
    for path in (directory / ".claude.json", directory / "settings.json"):
        data = json.loads(path.read_text()) if path.exists() else {}
        if path.name == ".claude.json":
            data.setdefault("theme", "dark")
            data["hasCompletedOnboarding"] = True
            project = data.setdefault("projects", {}).setdefault(str(Path.cwd().resolve()), {})
            project["hasTrustDialogAccepted"] = True
        else:
            for event, entries in hooks.items():
                own = data.setdefault("hooks", {}).setdefault(event, [])
                own.extend(entry for entry in entries if entry not in own)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data) + "\n")
        tmp.replace(path)
    os.environ["CLAUDE_CONFIG_DIR"] = str(directory)


if __name__ == "__main__":
    account_config()
    os.execvp(sys.argv[2], sys.argv[2:])
