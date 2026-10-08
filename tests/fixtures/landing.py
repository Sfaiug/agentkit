"""Land one crafted run through its saved line, with no real launches or process cleanup."""

from unittest.mock import patch

from agentkit import config, land, record, run, watch
# Job tests install this fixture in place of the handoff itself.
from agentkit.run import join_line


def local_owner_target(wt, upstream, *_args, **_kw):
    """These fake GitHub repositories keep their target in the fixture's Git refs."""
    ref = f"refs/remotes/{upstream}" if upstream.startswith("origin/") else upstream
    return run.git(wt, "rev-parse", f"{ref}^{{commit}}")


def landing(lp, deliver=None, *, checked=lambda: None, consume=None):
    """Join, run one lander pass and consume its verdict; a changed target stays queued."""
    (lp.run_dir / "task.md").write_text(
        f"# {lp.state['title']}\n\n## Done when\n```bash\n" + "\n".join(lp.cmds) + "\n```\n")
    with patch.object(land, "start_line"), patch.object(watch, "launch_resume"), \
            patch.object(run, "owner_target", side_effect=local_owner_target):
        def act():
            if deliver is None:
                return run.merge(lp)
            upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"
            return join_line(lp, upstream, deliver)

        if not (lp.state.get("waiting_on") or {}).get("line"):
            act()
        else:
            lp.state["state"] = "waiting"
            lp.write()
        if lp.state.get("state") != "waiting":
            return False
        turn = config.RUNS / lp.state["waiting_on"]["line"]
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
    with patch.object(run, "owner_target", side_effect=local_owner_target):
        return run.land(lp, upstream,
                        lambda: (run.integrate(lp, upstream)
                                 and ((lp.state.get("pr") and run.git(lp.wt, "rev-parse", "HEAD")
                                       == lp.state.get("delivery_sha"))
                                      or run.final_check(lp, upstream))), deliver)
