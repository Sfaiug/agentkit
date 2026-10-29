"""A seat rested past its harness's prompt cache sleeps, and while memory is tight the one at rest
the longest sleeps sooner; it wakes when its work comes back.

Which seat may sleep (`drowsiest`), sleep those due (`tick`), whether one sleeps (`asleep`), wake
it (`wake`).  Hidden: a seat rests from its turn's end while nothing but what it waits on moves it
(`_rests`); sleeping ends its tmux session, harness and scope's servers with it, marking it asleep
until it launches again or the owner closes it; waking is the reboot's resume, what waits to be
typed going in at the next quiet prompt; and anything but rest, work in its scope (`_busy`) or
held (`watch.cut_off`), an owner attached, a draft or a second pane keeps it awake."""

import math
from pathlib import PurePath
import re
import shlex
import time

from . import browser, config, gate, host, notify, orch, watch

AT_REST = ("idle", "done")
SHELLS = ("sh", "bash", "dash", "zsh", "ksh", "fish")
# tmux's own check as it kills: nobody attached since, and the harness's pane the only one
ALONE = "#{&&:#{==:#{session_attached},0},#{&&:#{==:#{session_windows},1},#{==:#{window_panes},1}}}"


def asleep(name):
    """Whether that seat was put to sleep since its harness launched, and not closed since."""
    name = config.resolve_session(name)
    record = config.session_records().get(name) or {}
    return ((record.get("asleep") or 0) > (record.get("launched") or 0)
            and not watch.seat_stopped_at(name))


def drowsiest(cfg):
    """The seat idle the longest that may sleep, as tmux lists it, or None."""
    resting = _resting(cfg)
    return min(resting)[2] if resting else None


def _resting(cfg):
    """(since when, name, session, record) of each seat at rest that may sleep, as tmux lists
    them."""
    kept, table = config.session_records(), watch._proc_table()
    return [(since, session["name"], session, record) for session in orch.sessions()
            if (since := _idle_since(cfg, session, record := kept.get(session["name"]), table))]


def _idle_since(cfg, session, record, table):
    """Since when that seat has rested and may sleep, or None: from its turn's end, or its
    harness's launch where that came later, as one woken has; only one whose conversation is
    its own, so that it comes back on it."""
    name = session["name"]
    live = watch.seat_read(name)
    if (record and orch.resumable(record, cfg) and orch.on_own_server(session)
            and not session["attached"] and not session["exited"]
            and live.get("state") == "at_prompt" and _rests(name, session, cfg, live)
            and not watch.cut_off(cfg, name)[0]
            and not _busy(session, table, record, cfg)):
        return live.get("began") and max(live["began"], record.get("launched") or 0)


def _rests(name, session, cfg, live):
    """Whether nothing but what that seat waits on moves it: it reads `idle` or `done`, or
    `working` on its waits alone (`watch.session_state`'s `waits`)."""
    answer = watch.session_state(name, session=session, cfg=cfg, live=live, previous=live)
    return answer["word"] in AT_REST or answer.get("waits", False)


def _sleep(record, cfg):
    """The `[sleep]` table of that seat's harness's adapter."""
    return config.manifest(orch.seat_harness(record, cfg)).get("sleep") or {}


def _busy(session, table, record, cfg):
    """Whether work runs beside the seat's harness: under the pane's first program, the shells
    tmux and the launch start it through above it, a process that is neither the harness ak's
    wrapper runs, nor ak's scope companion (`orch.SCOPE_ENDS`) or desktop server, which ends
    and starts again with its seat (`browser.DESKTOP`), nor one its adapter names as the
    harness's own (`[sleep] own`); or, in a scope of its own, a process the tree lost.  A
    harness whose adapter names none is never known idle."""
    own = _sleep(record, cfg).get("own")
    server = orch.seat_socket(session)
    pane = orch.harness_pane(session["name"], server)
    rc, pid = orch.tmux_out("display-message", "-p", "-t", pane, "#{pane_pid}", socket=server)
    if own is None or rc or not pid.isdigit():
        return True
    root = int(pid)
    children, reached, stack = {}, set(), [(root, False, False)]
    for child, (parent, _, _) in table.items():
        children.setdefault(parent, []).append(child)
    while stack:
        pid, below, wrapped = stack.pop()
        words = table.get(pid, (0, "", []))[2]
        shell = bool(words) and PurePath(words[0]).name.lstrip("-") in SHELLS
        if (below and not wrapped and orch.SCOPE_ENDS not in words
                and orch.program(words, full=True) != str(browser.DESKTOP)
                and not any(re.search(pattern, " ".join(words)) for pattern in own)):
            return True
        reached.add(pid)
        wrapper = orch.program(words) == "idle-compact.py"
        stack += [(child, below or not shell, wrapper) for child in children.get(pid, ())]
    group = host.process_cgroup(root)
    if not (group and PurePath(group).name.startswith("agentkit-seat-")):
        return False
    scope = host.cgroup_pids(group, complete=True)
    return scope is None or bool(set(scope) - reached)


def tick(cfg, log):
    """Every seat rested past its harness's prompt cache (`[sleep] cache`, in seconds) sleeps,
    and while memory is tight and none has, the one idle the longest sleeps sooner: one a tick."""
    tight, now = gate.memory_tight(), time.time()
    resting = sorted(_resting(cfg))
    due = [seat for seat in resting if now - seat[0] > _sleep(seat[3], cfg).get("cache", math.inf)]
    for since, name, session, _ in due or resting[:1] * bool(tight):
        # read again under the seat's typing lock: a line going in first may have started a turn,
        # and one that has ended since began a rest of its own
        with notify.session_lock(name):
            if _idle_since(cfg, session, config.session_records().get(name),
                           watch._proc_table()) != since:
                continue
            orch.tmux_out("if-shell", "-F", "-t", f"={name}:", ALONE,
                          f"kill-session -t {shlex.quote('=' + name)}",
                          socket=orch.seat_socket(session))
            if not orch.session_absent(name):
                continue
            config.update_session(name, asleep=time.time())
        log(f"put {name} to sleep, {tight or 'rested past its prompt cache'}")


def wake(name, log, cfg=None):
    """A sleeping seat back on its conversation as after a reboot.  Whether it is awake: one
    that does not come back stays asleep, tried again at what next wakes it."""
    if not asleep(name):
        return True
    try:
        orch.resume(config.load() if cfg is None else cfg, name, log=lambda _: None,
                    detached=True, hand_over=False)
    except (config.Error, OSError) as exc:
        log(f"WARN could not wake {name}: {exc}")
        return False
    log(f"woke {name}")
    return True
