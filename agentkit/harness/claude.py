"""Claude Code: a launcher-issued conversation, and the transcript it writes for it.

An alternate login also needs the seat's trust and hooks in its own config directory.
"""

from pathlib import Path
import hashlib
import json
import os
import re
import sys
import tempfile


def title_command(name):
    """Remote Control takes /rename live, including while a turn is running."""
    return f"/rename {name}"


def session_title(record):
    """Read only this seat's conversation, under the login its launch selected."""
    from .. import config

    conversation, cwd = record.get("conversation"), record.get("cwd")
    if not conversation or not cwd:
        return None
    account = record.get("account")
    directory = Path.home() / (f".claude-{account}" if account and account != "default"
                               else ".claude")
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    path = directory / "projects" / slug / f"{conversation}.jsonl"
    try:
        found = path.stat()
    except OSError:
        return None
    stamp = [found.st_dev, found.st_ino, found.st_size, found.st_mtime_ns, found.st_ctime_ns]
    # Cron starts a fresh process each tick, so the last reading lives on disk.
    cache = config.STATE / f"claude-title-{hashlib.sha256(str(path).encode()).hexdigest()}.json"
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = None
    if isinstance(cached, dict) and cached.get("stamp") == stamp:
        title = cached.get("title")
        return title if isinstance(title, str) and title.strip() else None
    title = None
    try:
        with path.open(encoding="utf-8") as transcript:
            for line in transcript:
                if '"custom-title"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(event, dict) and event.get("type") == "custom-title"
                        and event.get("sessionId") == conversation):
                    title = event.get("customTitle")
    except OSError:
        return None
    except UnicodeError:
        title = None
    try:
        _write(cache, {"stamp": stamp, "title": title})
    except OSError:
        pass        # a cache that cannot be written must not hide the title
    return title if isinstance(title, str) and title.strip() else None


def opened(cwd, conversation):
    """Has Claude Code written that conversation down yet, where it keeps them?

    Its directory per workspace: every character that is not a letter or a digit becomes a
    dash, and each transcript is named for the session it holds.  Claude Code writes the
    transcript at the first message and not at the prompt, so a seat nobody typed into has
    nothing to resume, and `--resume` on it is an error rather than a conversation.
    """
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    return (Path.home() / ".claude" / "projects" / slug / f"{conversation}.jsonl").exists()


def _write(path, data):
    """Replace a config file from a temp file no other launch shares.

    Seats open side by side, so a fixed temp name collides: one launch renames
    it away while another is still writing.  A replace inherits the temp file's
    mode rather than the old one's, so an existing file keeps the mode it had
    and a new one stays as mkstemp made it, 0600.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(data) + "\n")
        if path.exists():
            os.chmod(name, path.stat().st_mode & 0o777)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


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
            _write(path, data)
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
        _write(path, data)
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
