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


def handed_over(payload):
    """The background work a Stop hands over, as `background_tasks` or `backgroundTasks` -- an
    empty list when there is none -- or None from a harness whose Stop lists none."""
    found = payload.get("background_tasks")
    found = found if found is not None else payload.get("backgroundTasks")
    return found if isinstance(found, list) else None


def waits_on(payload):
    """Work this seat started in its own harness that has not reported back yet.

    A harness hands its Stop hook the agents and commands it still has in flight -- the ones
    whose task notification has not arrived.  Each of them wakes the seat again when it settles,
    so a stop on them is a wait.  A `monitor` is a watch, not work: the comment watch on an
    artifact the seat published stays in that list for the rest of the session, and counted, it
    held the seat working for days.  Nor is a `shell` in `background_tasks`: a background
    `sleep` or poll loop is no wait, since the harness kills it under memory pressure; a seat
    waits through `ak wait`.  Nor is a `terminal` or an `agent` a plugin adds, whose end starts
    no turn.  The other spelling's tasks count as before, their types never captured.
    """
    idle = (("monitor", "shell", "terminal", "agent") if payload.get("background_tasks") is not None
            else ("monitor",))
    return any(isinstance(task, dict) and task.get("type") not in idle
               for task in handed_over(payload) or ())


def stop_fact(session, payload, at, held=False):
    """The Stop of a payload handing over background work, heard `at`, as its one writer puts
    it down: hooks/orchestrator-stop.sh where the harness runs it, hooks/seat-state.sh on a
    harness that is nudged instead (`watch.stop_enforced`).  Its kind is `held` for a stop sent
    back and `background` for one waiting on work in flight; beside it, where there are any,
    `holds`: the type of each task still in flight, shells and monitors too (`held_work`)."""
    holds = [str(task.get("type") or "task") for task in handed_over(payload) or ()
             if isinstance(task, dict)]
    return {"session": session, "event": "Stop",
            "kind": "held" if held else "background" if waits_on(payload) else "",
            "text": "", "at": at, **({"holds": holds} if holds else {})}


def held_work(fact):
    """The type of each background task the seat's harness listed in flight at its last Stop
    (`stop_fact`), or [] -- as for a harness whose Stop lists none.  No move off an account
    with usage left cuts that work off."""
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
