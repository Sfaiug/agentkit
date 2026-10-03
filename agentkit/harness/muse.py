"""Muse Code: a channel installer beside its launcher, and a usage probe of its own.

Its screen, its stall words and its `[update]`/`[usage]` facts are data -- adapters/muse.toml.
What needs Python is what reads a file: the build its launcher installed, the probe response
agentkit/muse_usage.py cached, the quota a refused run recorded, whether a config.toml entry
is that probe's to run, and the session store a turn's tokens are written to.

No title hooks: 1.4.0-R4302.1 refuses /rename before and after a completed turn and
mid-turn ("naming is unavailable"), and rejects --name at launch. See the title fixtures;
a cleared composer is no receipt, and a command.invoked record is no custom name.
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


def _stem(account):
    """What one login's quota record and probe cache are named after: an account's are its own."""
    return f"usage-meta.{account}" if account else "usage-meta"


def record_turn(out, state_dir, account):
    """Keep a refused turn's quota without letting the box write ak's other records."""
    report = out / "quota.json"
    if report.exists():
        data = json.loads(report.read_text())
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / f"{_stem(account)}.json").write_text(json.dumps(data) + "\n")


def usage_extra(out, data, state_dir):
    """Muse's adapter strips its probe timestamp.

    Match the source before carrying its age into the snapshot; an unidentifiable response must
    not look newly measured.  `out["fetched_at"]` is already None -- `[usage] strips_timestamp`
    -- so a response nothing here recognises stays unmeasured.  An account's response names it,
    and is matched against that account's files alone.
    """
    from .. import usage   # here, not at the top: usage is what calls this
    account = data.get("account")
    stem = _stem(account if isinstance(account, str) else "")
    for filename in (f"{stem}.json", f"{stem}-probe.json"):
        path = state_dir / filename
        try:
            cached = json.loads(path.read_text())
            if (cached.get("meters") == data.get("meters")
                    and cached.get("error") == data.get("error")):
                out["fetched_at"] = (path.stat().st_mtime if filename == f"{stem}.json"
                                     else usage._number(cached.get("fetched_at")))
                break
        except (OSError, ValueError, TypeError, AttributeError):
            pass


def usage_recorded(state_dir, now):
    """The quota imported from a refused turn's adapter report, for as long as it stands.

    Each meter is trusted for at most its own window, as the adapter's `usage` verb trusts it.
    Where `[providers.meta]` lists accounts every login has a record of its own, and nothing
    here says which row is being read: none is applied, and each reaches its own row through
    that account's `usage` verb, which answers with it first.
    """
    try:
        if config.accounts(config.load(), "meta"):
            return []
    except config.Error:
        pass
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
