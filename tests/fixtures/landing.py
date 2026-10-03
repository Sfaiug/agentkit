"""Land one crafted run through its saved line, with no real launches or process cleanup."""

from unittest.mock import patch

from agentkit import land, record, run, watch


def landing(lp, deliver=None, *, checked=lambda: None, consume=None):
    """Join, run one lander pass and consume its verdict; a changed target stays queued."""
    upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"
    (lp.run_dir / "task.md").write_text(
        f"# {lp.state['title']}\n\n## Done when\n```bash\n" + "\n".join(lp.cmds) + "\n```\n")
    # Existing tests craft their records wherever their sandbox helper kept them.
    with patch.object(record, "run_dirs", return_value=[lp.run_dir]), \
            patch.object(record, "process_active", return_value=False), \
            patch.object(land, "start_line"), patch.object(watch, "launch_resume"):
        act = (lambda: run.join_line(lp, upstream, deliver)) if deliver else lambda: run.merge(lp)
        if not (lp.state.get("waiting_on") or {}).get("line"):
            act()
        if lp.state.get("state") != "waiting":
            return False
        turn = run.turn_path(lp, upstream)
        land.check_line(turn, lp.log)
        lp.state = record.read_state(lp.run_dir)
        checked()
        if not any(key in lp.state["waiting_on"] for key in ("land", "fix")):
            return False
        if consume:
            return consume(lp)
        lp.state["state"] = "running"
        lp.write()
        return act()
