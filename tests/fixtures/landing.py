"""Land one crafted run through its saved line, with no real launches or process cleanup."""

from unittest.mock import patch

from agentkit import land, record, run, watch


def landing(lp, deliver=None, *, checked=lambda: None, consume=None, join=run.join_line):
    """Join, run one lander pass and consume its verdict; a changed target stays queued."""
    if not (lp.state.get("waiting_on") or {}).get("line"):
        run.require_review_pass(lp)
    upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"
    (lp.run_dir / "task.md").write_text(
        f"# {lp.state['title']}\n\n## Done when\n```bash\n" + "\n".join(lp.cmds) + "\n```\n")
    with patch.object(land, "start_line"), patch.object(watch, "launch_resume"):
        act = (lambda: join(lp, upstream, deliver)) if deliver else lambda: run.merge(lp)
        if not (lp.state.get("waiting_on") or {}).get("line"):
            act()
        else:
            lp.state["state"] = "waiting"
            lp.write()
        if lp.state.get("state") != "waiting":
            return False
        turn = run.turn_path(lp, upstream)
        # Limit checker fakes to the pass: delivery may wait while a job builds its dependant.
        active = record.process_active
        with patch.object(record, "run_dirs", return_value=[lp.run_dir]), \
                patch.object(record, "process_active", side_effect=lambda state:
                             False if state.get("run_id") == lp.state.get("run_id") else active(state)):
            land.check_line(turn, lp.log)
        saved = record.read_state(lp.run_dir)
        lp.state.clear()
        lp.state.update(saved)
        checked()
        if not any(key in lp.state["waiting_on"] for key in ("land", "fix")):
            return False
        if consume:
            return consume(lp)
        lp.state["state"] = "running"
        lp.write()
        return act()


def fork_landing(lp):
    """Exercise the verification and lock path retained for forks, with fixture PR delivery."""
    upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"

    def deliver():
        if not run.push(lp):
            return False
        url = run.open_pr(lp, upstream.removeprefix("origin/"))
        return bool(url and run.wait_checks(lp, url) and run.do_merge(lp, url, upstream))

    return fork_turn(lp, upstream, deliver)


def fork_turn(lp, upstream, deliver):
    """The line handoff's stand-in for tests of the integration path retained for forks."""
    return run.land(lp, upstream,
                    lambda: (run.integrate(lp, upstream)
                             and ((lp.state.get("pr") and run.git(lp.wt, "rev-parse", "HEAD")
                                   == lp.state.get("delivery_sha"))
                                  or run.final_check(lp, upstream))), deliver)
