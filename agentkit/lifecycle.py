"""Recorded lifecycle events and their meaning, without screen or notification machinery.

A callback and the watcher read the same facts and manifest. Keeping that read here lets a
completed tool check whether it answered a question without starting the watcher's imports.
"""
import json
import math

from . import config

LIVE = ("asking", "working", "at_prompt", "draft")


def facts(name):
    """The last lifecycle event that seat's own harness reported, or {}."""
    try:
        data = json.loads(config.hook_facts_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError, config.Error):
        return {}
    return data if isinstance(data, dict) else {}


def held_work(fact):
    """The type of each background task the seat's harness listed in flight at its last Stop
    (hooks/orchestrator-stop.sh), or [] -- as for a harness whose Stop lists none."""
    holds = fact.get("holds") if isinstance(fact, dict) else None
    return [str(task) for task in holds] if isinstance(holds, list) else []


def carried(standing, fact):
    """`fact`, holding the background work the fact `standing` names unless it is the next Stop,
    which lists that work again: a prompt or a compaction ends none of it.  A new harness's
    first fact finds none standing (`orch.resume` moves the last one aside)."""
    work = held_work(standing)
    return {**fact, "holds": work} if work and fact.get("event") != "Stop" else fact


def state(harness, fact):
    """(state, event, evidence, when) the manifest maps that fact to, or (None, "", "", None).

    The hook records the event and its payload; which state it means is the manifest's to say,
    so no harness's vocabulary is spelled out here.
    """
    if not isinstance(fact, dict):
        return None, "", "", None
    event, kind, when = fact.get("event"), fact.get("kind") or "", fact.get("at")
    if (not isinstance(event, str) or not isinstance(when, (int, float))
            or isinstance(when, bool) or not math.isfinite(when)):
        return None, "", "", None
    hooks = config.manifest(harness).get("hooks")
    for entry in (hooks or {}).get("event") or ():
        if not isinstance(entry, dict) or entry.get("name") != event:
            continue
        kinds = entry.get("kinds")
        if isinstance(kinds, list) and kind not in kinds:
            continue
        if entry.get("state") in LIVE:
            text = str(fact.get("text") or "").strip()
            return (entry["state"], f"{event}/{kind}" if kind else event,
                    " ".join((text or event).split())[:160], float(when))
    return None, "", "", None
