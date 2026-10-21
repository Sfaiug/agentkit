"""agentkit: `ak` shows each seat as working, needs you, done or idle, and `ak run task.md` delivers a merged PR.

A seat is a harness's TUI in tmux, recorded in `session-<name>.json`; a run is one task (build,
done-when, review, merge, hand-back), recorded in `~/.agentkit/runs/<id>/run.json`.  All state is
files under `~/.agentkit`, kept moving by the `ak watch` tick.  A harness is a plugin: a script
and a manifest in adapters/, an optional module, a config entry.  `run.py` holds most of a run;
every module opens by saying what it hides, so the code is its own map.
"""
