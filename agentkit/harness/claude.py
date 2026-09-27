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


def account_config(check=False):
    """Keep the owner's configuration beside an alternate login's own credentials.

    Claude's config override moves both its user settings and its global .claude.json.
    Validate before respawning the pane; prepare trust again in the launch's actual cwd.
    Every seat runs bypass permissions: an accepted auto-mode offer writes `auto` into
    the settings, so each launch pins it back and leaves the offer answered.
    """
    account = os.environ.get("AGENTKIT_ACCOUNT")
    if not account:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        home = Path.home()
        paths = (home / ".claude/settings.json", home / ".claude.json")
        values = [json.loads(path.read_text()) if path.exists() else {} for path in paths]
        if not all(isinstance(value, dict) for value in values):
            raise ValueError("Claude settings and global config must be JSON objects")
        if check:
            return
        permissions = values[0].setdefault("permissions", {})
        if not isinstance(permissions, dict):
            permissions = values[0]["permissions"] = {}
        permissions["defaultMode"] = "bypassPermissions"
        values[1]["hasSeenAutoDefaultNudge"] = True
        paths[0].parent.mkdir(parents=True, exist_ok=True)
        for path, data in zip(paths, values):
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data) + "\n")
            tmp.replace(path)
        return
    home = Path.home()
    directory = home / f".claude-{account}"
    settings = home / ".claude/settings.json"
    paths = (settings, directory / ".claude.json", directory / "settings.json")
    values = [json.loads(path.read_text()) if path.exists() else {} for path in paths]
    if not all(isinstance(value, dict) for value in values):
        raise ValueError("Claude settings and global config must be JSON objects")
    if check:
        return
    directory.mkdir(parents=True, exist_ok=True)
    try:
        usual = json.loads((home / ".claude.json").read_text())
    except (OSError, ValueError):
        usual = {}
    if not isinstance(usual, dict):
        usual = {}
    for path, data in zip(paths[1:], values[1:]):
        if path.name == ".claude.json":
            # A notice answered once is answered everywhere: only `true` flags travel,
            # so the named login keeps its own account, ids, caches and projects.
            for key, value in usual.items():
                if value is True:
                    data[key] = True
            data["hasSeenAutoDefaultNudge"] = True
            data.setdefault("theme", "dark")
            data["hasCompletedOnboarding"] = True
            project = data.setdefault("projects", {}).setdefault(str(Path.cwd().resolve()), {})
            project["hasTrustDialogAccepted"] = True
        else:
            data.update(values[0])
            # Hooks belong to the current installation, not every past checkout.
            data["hooks"] = values[0].get("hooks", {})
            permissions = data.setdefault("permissions", {})
            if not isinstance(permissions, dict):
                permissions = data["permissions"] = {}
            permissions["defaultMode"] = "bypassPermissions"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data) + "\n")
        tmp.replace(path)
    for name in ("CLAUDE.md", "agents", "skills", "commands", "plugins"):
        source, target = home / ".claude" / name, directory / name
        if source.exists() and not target.exists() and not target.is_symlink():
            target.symlink_to(source, target_is_directory=source.is_dir())
    os.environ["CLAUDE_CONFIG_DIR"] = str(directory)


if __name__ == "__main__":
    checking = sys.argv[1:] == ["--check"]
    account_config(check=checking)
    if not checking:
        os.execvp(sys.argv[2], sys.argv[2:])
