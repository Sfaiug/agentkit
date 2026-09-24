"""Muse Code: a channel installer beside its launcher, and a usage probe of its own.

Its screen, its stall words and its `[update]`/`[usage]` facts are data -- adapters/muse.toml.
What needs Python is what reads a file: the build its launcher installed, the probe response
agentkit/muse_usage.py cached, the quota a refused run recorded, whether a config.toml entry
is that probe's to run, and the session store a turn's tokens are written to.
"""

import json
import os
import re
from pathlib import Path

from .. import config


def identity(text, argv):
    """Muse's release label plus the build its launcher actually installed.

    The label alone does not identify a build: the launcher records that beside itself, so a
    frozen installed release can still be told from the next one.
    """
    launcher = config.harness_binary(argv[0])
    try:
        build = (Path(launcher).resolve(strict=True).parent / ".muse-version").read_text().strip()
    except (OSError, RuntimeError, TypeError):
        build = ""
    return f"{text} (installed build {build})" if build and build not in text else text


def usage_extra(out, data, state_dir):
    """Muse's adapter strips its probe timestamp.

    Match the source before carrying its age into the snapshot; an unidentifiable response must
    not look newly measured.  `out["fetched_at"]` is already None -- `[usage] strips_timestamp`
    -- so a response nothing here recognises stays unmeasured.
    """
    from .. import usage   # here, not at the top: usage is what calls this
    for filename in ("usage-meta.json", "usage-meta-probe.json"):
        path = state_dir / filename
        try:
            cached = json.loads(path.read_text())
            if (cached.get("meters") == data.get("meters")
                    and cached.get("error") == data.get("error")):
                out["fetched_at"] = (path.stat().st_mtime if filename == "usage-meta.json"
                                     else usage._number(cached.get("fetched_at")))
                break
        except (OSError, ValueError, TypeError, AttributeError):
            pass


def usage_recorded(state_dir, now):
    """The quota adapters/muse.sh recorded when a run was refused, for as long as it stands.

    Each meter is trusted for at most its own window, as the adapter's `usage` verb trusts it.
    """
    path = state_dir / "usage-meta.json"
    try:
        age = now - path.stat().st_mtime
        return [meter for meter in json.loads(path.read_text())["meters"]
                if meter["resets_at"] > now and meter["window_secs"] > age]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def usage_policy(entry, effort):
    """The probe uses a config.toml model key and effort of this harness, with no fallback."""
    return (isinstance(entry.get("model"), str) and bool(entry["model"])
            and isinstance(effort, str) and bool(effort))


def tokens(out):
    """What the turn in `out` spent, read from Muse's own session store, or None.

    `muse exec --json` streams no usage at all.  The stream names the session and the run the
    turn opened; the session's session.jsonl, under ~/.local/share/muse/sessions/YYYY/MM/DD/,
    records a provider usage for every model request, owned by that run -- earlier turns of a
    resumed session are other runs.  Input tokens already include the cached prefix.
    """
    session, runs = None, set()
    try:
        with (out / "events.jsonl").open(errors="replace") as source:
            for line in source:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                stream = event.get("stream") if isinstance(event, dict) else None
                if isinstance(stream, dict) and stream.get("kind") == "session":
                    session = session or stream.get("id")
                payload = event.get("payload") if isinstance(event, dict) else None
                linked = payload.get("run_stream") if isinstance(payload, dict) else None
                if isinstance(linked, dict) and isinstance(linked.get("id"), str):
                    runs.add(linked["id"])
    except OSError:
        return None
    if not isinstance(session, str) or not re.fullmatch(r"[\w-]+", session) or not runs:
        return None
    root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "muse/sessions"
    total, seen = 0, False
    for path in root.glob(f"*/*/*/{session}/session.jsonl"):
        try:
            with path.open(errors="replace") as source:
                for line in source:
                    if "goal_usage_attribution" not in line:
                        continue
                    try:
                        payload = json.loads(line).get("payload") or {}
                        record = payload["event"]["record"]
                        quantity = record["quantity"]
                        if (record.get("usage_family") != "provider"
                                or record["owner"].get("run_id") not in runs
                                or quantity.get("reported") is False):
                            continue
                        counts = [quantity.get(key) for key in ("input_tokens", "output_tokens")]
                    except (ValueError, TypeError, KeyError, AttributeError):
                        continue
                    counts = [count for count in counts
                              if isinstance(count, int) and not isinstance(count, bool)
                              and count >= 0]
                    if counts:
                        total, seen = total + sum(counts), True
        except OSError:
            continue
    return total if seen else None
