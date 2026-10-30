"""Who executes and who reviews a run.

The models a session marks for each role, ordered by the usage they have left,
the pair a round gets and the refusals when none fits, the hand to the next
executor when one spends its window, and the words a run waiting on a reviewer
or an exhausted provider shows.
"""

import json
import time

from . import config, transitions, turns, update


def collect_usage(cfg):
    """The usage read every pick of a run starts from, its harnesses asked if they can run.

    A concurrent cache publisher must not abort a run that already owns a slot.
    """
    from . import usage  # here, not at the top: usage imports staffing
    try:
        read = usage.collect(cfg)
    except FileNotFoundError as exc:
        cache = config.STATE / "usage.json"
        if (exc.filename != str(cache.with_suffix(".tmp")) or
                exc.filename2 != str(cache)):
            raise
        # collect uses a shared temporary filename. Another reader can publish it
        # first; re-read its snapshot through the normal freshness checks.
        # Retry once only: a persistent filesystem failure still propagates.
        read = usage.collect(cfg)
    return usage.readiness(cfg, read)


def handover_executor(state, cfg, reason, dry=(), log=None):
    """Hand a worker turn to the best pair on a provider that refused nothing yet.

    Returns the new executor, or None where none is eligible.  Both roles are re-picked
    as one pair (`best_pair`), so tier beats budget and the pair is always a legal one --
    a reviewer kept from before can be the very model now executing.  A refused provider
    never gets the work back (that is how a handover becomes a circle); its reviewers
    are considered only when no pair forms without them.  Records the move
    in `executor_history` with the reason (`stalled`, `dry`); an attempt that finds nobody
    records nothing, since the same worker carries on. `dry` is every provider that
    already refused this piece of work.
    Later re-picks follow the normal order; this preference applies only at handover.
    """
    current = state.get("executor")
    try:
        current_provider = config.model(cfg, current)["provider"] if current else None
    except config.Error:
        current_provider = None
    refused = set(dry)
    if current_provider is not None:
        refused.add(current_provider)
    new = reviewer = None
    try:
        providers = collect_usage(cfg)
        workers = run_workers(cfg, state)
        reviewers = run_reviewers(cfg, state)
        order = [n for n in ready_order(cfg, providers, workers, log, reviewers=reviewers)
                 if n != current and config.model(cfg, n)["provider"] not in refused]
        review_order = ready_order(cfg, providers, reviewers, role="reviewer")
        pair = best_pair(cfg, order, [n for n in review_order
                                     if config.model(cfg, n)["provider"] not in refused])
        if pair is None:
            pair = best_pair(cfg, order, review_order)
        if pair is not None:
            new, reviewer = pair
    except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    if new is None:
        return None
    state.setdefault("executor_history", []).append(
        {"at": time.time(), "from": current, "to": new, "reason": reason})
    state["executor"] = new
    state["exec_session"] = None
    replace_reviewer(state, reviewer)
    return new


def replace_reviewer(state, reviewer):
    """`reviewer` reviews the run from here, fresh: the conversation of the one it replaces,
    and a review attempt that one left open, are not its own (`handed`, read by `review`)."""
    if reviewer != state.get("reviewer"):
        state["reviewer"], state["review_session"] = reviewer, None
        if state.get("review_pending"):
            state["review_pending"]["handed"] = True


def ready_order(cfg, providers, workers=None, log=None, **kwargs):
    """`usage.pick_order` over the workers whose harness can run a turn here.

    Every pick a run makes -- executor, reviewer, spare, handover, the fixer's -- comes
    through here.  A worker whose harness is not installed or not logged in is left out
    before any budget rule reads the list, so a subscription nobody can run keeps no payg
    provider out; `log`, on the one call of a pick that gives a role, says so in one line.
    """
    from . import usage  # here, not at the top: usage imports staffing
    skip = {}
    if getattr(providers, "harnesses", None):
        skip = {name: usage.unready(cfg, name, providers) for name in config.offered(cfg)}
        skip = {name: why for name, why in skip.items() if why}
    if kwargs.get("role") == "reviewer":
        skip.update((name, why) for name in config.offered(cfg) if (why := barred_reviewer(cfg, name)))
    if log and skip:
        listed = (config.reviewers(cfg) if kwargs.get("role") == "reviewer"
                  else config.workers(cfg)) if workers is None else workers
        for name in listed:
            if name in skip:
                log(f"skipped {name}: {skip[name]}")
    return usage.pick_order(cfg, providers, workers, skip=skip, **kwargs)


def barred_reviewer(cfg, name):
    """Why this model never reviews, or None.  A reviewer judges a branch by the base's rules,
    which ak puts in its prompt; a harness that loads the checkout's own instruction files
    (`config.workspace_rules`) would read what the branch wrote instead.  An executor is never
    barred: the branch's instructions are its own."""
    files = config.workspace_rules(config.model(cfg, name)["harness"])
    return f"its harness loads the branch's own {', '.join(files)}" if files else None


def barred_refusal(cfg, names):
    """The one sentence a selection is refused with when every reviewer in it is barred
    (`barred_reviewer`), or None.  A task's launch and an own pull request's review alike."""
    barred = {name: barred_reviewer(cfg, name) for name in names}
    if not names or not all(barred.values()):
        return None
    return (f"none of the reviewers {', '.join(names)} may review: "
            + "; ".join(f"{name}: {why}" for name, why in barred.items())
            + "; mark a reviewer on another harness")


def refuse_unready(cfg, providers, name, role="executor"):
    """A model named outright whose harness cannot run here, or that may not take the role, is
    refused, in one sentence.

    Not on an answer an install or revert of that harness overlapped: its command was missing
    then, so the swap is waited out and the harness asked again, as a failed turn's is.
    """
    from . import usage  # here, not at the top: usage imports staffing
    why = usage.unready(cfg, name, providers)
    entry = config.model(cfg, name)
    harness = entry["harness"]
    if why and update.swap_end(harness, providers.asked_at, time.time()):
        while (end := update.swap_end(harness, providers.asked_at, time.time()) or 0) > (
                now := time.time()):
            time.sleep(min(turns.SWAP_POLL, end - now))
        why = usage.harness_unready(harness, provider=entry["provider"])
    if why:
        raise config.Error(f"{name} cannot run here: {why}")
    if role == "reviewer" and (why := barred_reviewer(cfg, name)):
        raise config.Error(f"{name} cannot review: {why}")


def refuse_outside_group(cfg, name, group, role):
    if name:
        config.model(cfg, name)
        if group is not None and name not in group:
            raise config.Error(f"{name!r} is not a {role} of this run "
                               f"({role}s: {', '.join(group)})")


def pick_models(cfg, providers, want_exec, want_review, log, *, resuming=False, quiet=False,
                repo=None, workers=None, reviewers=None):
    """Pick each role within its launch list, refusing an explicit name outside that group."""
    workers, reviewers = config.role_groups(cfg, workers, reviewers)
    if reviewers is not None:
        refuse_outside_group(cfg, want_review, reviewers, "reviewer")
    order = ready_order(cfg, providers, workers, None if want_exec and want_review else log,
                        quiet=quiet, repo=repo, reviewers=reviewers)
    session = config.active_session(cfg)
    allowed = workers if workers is not None else (session["workers"] if session else None)
    if want_exec:
        config.model(cfg, want_exec)
        # Legacy callers without a bound list retain the default orchestrator on resume.
        admitted = (workers is None and session
                    and session["orchestrator"] == want_exec == cfg["defaults"]["orchestrator"]
                    and (resuming or want_exec in order))
        if allowed is not None and want_exec not in allowed and not admitted:
            where = f"session {session['name']!r}" if session else "this run"
            raise config.Error(f"{want_exec!r} is not a worker of {where}")
        refuse_unready(cfg, providers, want_exec)
    elif not order:
        raise turns.QuotaDry("every worker has a gate meter at 100% used")
    executor = want_exec or order[0]
    if want_review:
        config.model(cfg, want_review)
        if reviewers is None and allowed is not None and want_review not in allowed:
            where = f"session {session['name']!r}" if session else "this run"
            raise config.Error(f"{want_review!r} is not a worker of {where}")
        refuse_unready(cfg, providers, want_review, "reviewer")
        reviewer = want_review
        if want_exec is None:
            # A named reviewer takes the best executor for it: tier first, then
            # budget, through the same pair choice every automatic pick uses.
            pair = best_pair(cfg, order, [reviewer])
            if pair is not None:
                executor = pair[0]
    else:
        review_order = ready_order(cfg, providers, reviewers if reviewers is not None else workers,
                                   role="reviewer", quiet=quiet, repo=repo)
        pair = best_pair(cfg, [want_exec] if want_exec else order, review_order)
        if pair is None:
            where = f" for executor {want_exec}" if want_exec else ""
            raise turns.QuotaDry("no eligible reviewer: no worker with budget is left to review"
                           f"{where}; waiting for review")
        executor, reviewer = pair
    transitions.review_providers(cfg, executor, reviewer)
    return executor, reviewer


def pair_refusal(cfg, providers, workers, want_exec=None, want_review=None, reviewers=None):
    """The one sentence a launch is refused with when no worker can run, or None.

    Budgets are left out: a spent meter refills, and a run waiting on one is parked for a
    reason.  Nothing refills a harness that is not installed or not logged in, so a launch
    left with no runnable executor or reviewer is refused instead of parking on a review
    nobody can give, and so is one whose every reviewer is barred from reviewing
    (`barred_reviewer`).  One runnable worker is enough to launch: it reviews its own work,
    marked self-reviewed.  Legacy explicit names remain unbound; only automatic candidates
    fall back to the configured worker selection.
    """
    from . import usage  # here, not at the top: usage imports staffing
    listed, review_list = config.role_groups(cfg, workers, reviewers)
    bound_exec = listed is not None
    bound_review = review_list is not None or bound_exec
    listed = config.workers(cfg) if listed is None else listed
    review_list = listed if review_list is None else review_list
    skipped = {name: usage.unready(cfg, name, providers) for name in [*listed, *review_list]}
    ready = [name for name in listed if not skipped[name]]
    reviews = [name for name in review_list if not skipped[name] and not barred_reviewer(cfg, name)]
    if want_exec:
        ready = [name for name in ready if name == want_exec] if bound_exec else [want_exec]
    if want_review:
        reviews = ([name for name in reviews if name == want_review]
                   if bound_review else [want_review])
    if any(reviewer_order(cfg, name, reviews) for name in ready):
        return None
    if barred := barred_refusal(cfg, [want_review] if want_review else review_list):
        return barred
    why = "; ".join(f"{name}: {reason}" for name, reason in skipped.items() if reason)
    missing = []
    if not ready:
        missing.append(f"workers {', '.join(listed)}")
    if not reviews:
        missing.append(f"reviewers {', '.join(review_list)}")
    if not missing:  # an unknown explicit name refuses below; name both lists
        missing = [f"workers {', '.join(listed)}",
                   f"reviewers {', '.join(review_list)}"]
    return (f"none of the {' and '.join(missing)} can run here"
            + (f" ({why})" if why else "")
            + "; log in to another harness or add another model to the groups")


def same_model(cfg, first, second):
    """Whether two worker names are the same model: the same name, or the same provider
    and model id under another name -- the `sonnet-2` the `c` screen adds an already
    configured model as at another effort."""
    if not first or not second:
        return False
    if first == second:
        return True
    try:
        one, two = config.model(cfg, first), config.model(cfg, second)
    except config.Error:
        return False
    return one["provider"] == two["provider"] and one["model"] == two["model"]


def reviewer_order(cfg, writers, order):
    """The order given, by each reviewer's worst `pair_tier` beside the writers.  `writers`
    is the model that wrote the work, or every model that wrote part of it: a PR's
    orchestrator and the fixer its fix was handed to.  A model tends to miss the mistakes it
    makes, so its own review is the last choice -- but only a choice, never a refusal: one
    worker reviews itself."""
    names = [writers] if isinstance(writers, str) else [name for name in (writers or []) if name]
    try:
        for name in names:
            config.model(cfg, name)
    except config.Error:
        return []
    tiered = []
    for name in order:
        try:
            config.model(cfg, name)
        except config.Error:
            continue
        tiered.append((max((pair_tier(cfg, each, name) for each in names), default=0), name))
    return [name for _, name in sorted(tiered, key=lambda each: each[0])]


def head_writers(state):
    """Every model that wrote part of the head a review judges: a seat's own PR's orchestrator,
    the executor or fixer of the moment, and every model a turn was handed from or to
    (`executor_history`), so none of them is the first choice to review it."""
    names = [state.get("own_orchestrator") if state.get("own_pr") else None, state.get("executor"),
             *(entry.get(key) for entry in state.get("executor_history") or [] for key in ("from", "to"))]
    return list(dict.fromkeys(name for name in names if name))


def pair_tier(cfg, executor, reviewer):
    """This pair's tier, in the owner's order of 21 Oct (AGENTS.md, Owner rules): 0 a model
    on another provider, 1 another model on the executor's provider, 2 the executor's own
    model.  Own is `same_model`'s: one model id under two providers is two models.

    None when either name is unknown: no pick weighs a pair it cannot name.
    """
    if same_model(cfg, executor, reviewer):
        return 2
    try:
        same = config.model(cfg, executor)["provider"] == config.model(cfg, reviewer)["provider"]
    except config.Error:
        return None
    return 1 if same else 0


def best_pair(cfg, executors, reviewers, allow_self=True):
    """The pair every automatic pick takes: tier first, then executor order, then reviewer.

    Both lists are already in pick order (`usage.pick_order`), so the first pair in tier
    order wins: a review by another provider's model beats one by the executor's provider,
    which beats the executor reviewing itself.  A pick that stopped at the first executor
    would keep a worse tier while a better pair is ready.  None when no pair forms -- or
    only a self-review when `allow_self` is off, which a flake waits out.
    """
    best, key = None, None
    for ei, executor in enumerate(executors or []):
        for ri, reviewer in enumerate(reviewers or []):
            tier = pair_tier(cfg, executor, reviewer)
            if tier is None or (tier == 2 and not allow_self):
                continue
            found = (tier, ei, ri)
            if key is None or found < key:
                key, best = found, (executor, reviewer)
    return best


def self_reviewed(state, cfg=None):
    """Whether the executor's own model reviews this run: the recorded review's pair
    where a round was reviewed, else the current one.  A seat's own PR has no executor,
    so its writer -- the seat's orchestrator -- counts as the executor.  `cfg` tells an
    alias (the same provider and model id under another name) from another model;
    without it only the same name counts."""
    evidence = state.get("review") if isinstance(state.get("review"), dict) else {}
    reviewer = evidence.get("reviewer") or state.get("reviewer")
    executor = evidence.get("executor")
    if executor is None:
        executor = state.get("own_orchestrator") if state.get("own_pr") else state.get("executor")
    if not reviewer or not executor or reviewer == executor:
        return bool(reviewer and reviewer == executor)
    return cfg is not None and same_model(cfg, executor, reviewer)


def started_round(run_dir, state):
    """The last round anything actually ran in: its round directory is the record of it.

    A round that was cut short leaves no summary but does leave the directory its executor
    wrote in, so the model that held it is credited with it rather than with nothing.
    """
    started = [int(path.name[len("round-"):]) for path in run_dir.glob("round-*")
               if path.name[len("round-"):].isdigit()]
    return max([*started, len(state.get("round_summaries") or [])], default=0)


def note_handover(state, before, why, rnd, to=None, reason="dry"):
    """Record in run.json which model held which rounds, and why the work changed hands.

    Two models that shared a round both held it: a handover mid-round is what this is, so the
    outgoing model's rounds start at the round it took over in -- the last round its own
    predecessor held -- and not at the one after it.  Anything else loses the round of whoever
    took over second, and of every model after that.

    The model taking over starts a fresh session: the context the old one built lives on a
    provider that is spent, and there is nothing there to resume.

    Every entry this function writes names the move both ways -- `from`/`to`/`reason` for
    the handover the tick records, `model`/`rounds`/`why` for the rounds each model held.
    The tick's own entries carry only the first half, so both readers fall back to it: the
    status line reads `from` where `model` is missing and `reason` where `why` is, and the
    rounds here start at the round being handed over, crediting the outgoing model with
    only the round it plainly held rather than every round since the run began.
    """
    history = state.setdefault("executor_history", [])
    last = history[-1] if history else None
    if last is not None and last.get("rounds"):
        took_over = last["rounds"][-1]
    elif last is not None:
        took_over = rnd
    else:
        took_over = 1
    history.append({"from": before, "to": before if to is None else to, "reason": reason,
                    "model": before, "rounds": list(range(took_over, rnd + 1)), "why": why})
    state["exec_session"] = None


def next_executor(cfg, providers, dry, reviewer, log, repo=None, workers=None, reviewers=None,
                  allow_self=True):
    """(executor, reviewer) for work whose provider has run dry, or turns.Exhausted when none is left.

    Both roles are re-picked as one pair (`best_pair`), so tier beats budget: a review by
    another model beats a self-review.  Keeping the current reviewer
    instead would force a dearer executor on the run -- on 2026-09-22 a Grok refusal kept
    reviewer Muse and pushed execution onto Claude, though executor Muse with reviewer Claude
    was legal and cheaper.

    `dry` is every provider that has already refused this piece of work, not just the last one:
    a refusal the meters cannot see is still a refusal, and handing the work back to a provider
    that has just turned it down is how a handover becomes a circle.  `workers`, when given,
    is the run's bound list: nothing outside it is ever picked.  `allow_self` False keeps a
    flaky provider's handover off a self-review pair: the flake usually answers after a wait,
    so only a provider that cannot run the work settles for one.
    """
    workers, reviewers = config.role_groups(cfg, workers, reviewers)
    order = [n for n in ready_order(cfg, providers, workers, log, repo=repo, reviewers=reviewers)
             if config.model(cfg, n)["provider"] not in dry]
    review_order = [n for n in ready_order(cfg, providers,
                                          reviewers if reviewers is not None else workers,
                                          role="reviewer", repo=repo)
                    if config.model(cfg, n)["provider"] not in dry]
    pair = best_pair(cfg, order, review_order, allow_self=allow_self)
    if pair is not None:
        return pair
    raise turns.QuotaDry(f"nothing is left to execute with a legal reviewer: "
                   f"{', '.join(sorted(dry))} ran dry; resume when a meter refills")


def hand_executor(lp, why, detail, dry):
    """Give this round's work to a model on a provider that refused nothing yet.

    The work keeps its identity: the same worktree, the same branch, the same round number and
    the same round budget.  Only the model changes, and it changes in run.json too, so what
    `ak run status` shows and what the result reads is who really did which round.

    Returns the new executor, or None where none is eligible.  An attempt that finds nobody
    records nothing: the same worker carries on, and run.json would otherwise show a handover
    that never happened.  `dry` is every provider that already refused this piece of work, not
    just the last one -- handing the work back to one of those is how a handover becomes a
    circle -- so the caller's set grows here and stays grown for the rest of the round.
    """
    before = lp.executor
    workers = run_workers(lp.cfg, lp.state)
    reviewers = run_reviewers(lp.cfg, lp.state)
    try:
        dry.add(config.model(lp.cfg, before)["provider"])
    except config.Error:
        pass
    try:
        providers = collect_usage(lp.cfg)
        # Only "transient" may still answer where it is: a flake waits out the backoff
        # unless another model can take the role with an independent review beside it.
        new, reviewer = next_executor(lp.cfg, providers, dry, lp.reviewer, lp.log,
                                      lp.state.get("repo"), workers, reviewers,
                                      allow_self=why != "transient")
    except (turns.Exhausted, config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        new = None
    rnd = started_round(lp.run_dir, lp.state)
    if new is None:
        return None
    note_handover(lp.state, before, why, rnd, to=new, reason="dry")
    lp.executor, lp.exec_sid = new, None
    previous = lp.reviewer
    if reviewer != previous:
        lp.reviewer, lp.review_sid = reviewer, None
    lp.save()
    if why == "refused":
        message = detail.removeprefix("refused: ")
        lp.log(f"{before} refused: {message}; handing over to {new}")
    else:
        lp.log(f"handing executor to {new}: {before} {detail}")
    if reviewer != previous:
        lp.log(f"reviewer re-picked for executor {new}: {previous} -> {reviewer}")
    return new


def run_workers(cfg, state):
    """The executor list this run is bound to: its session's selection at launch.

    Every executor of the run -- first pick, every handover and every fixer -- is picked
    from this list and never widened.  `run.json` records what the session held when the run
    was launched, because the session record can be rewritten while the run lives and the
    process doing a later pick may speak for another seat or for none.  A receipt written
    before the field existed reads its launch session's selection now.  None means no
    selection was ever recorded anywhere, and the pick falls back as it always did.
    """
    workers = state.get("workers")
    if isinstance(workers, list) and workers:
        return list(workers)
    try:
        name = transitions.launched_session(state)
        selection = config.load_session(cfg, name, required=False) if name else None
    except config.Error:
        selection = None
    workers = (selection or {}).get("workers")
    return list(workers) if isinstance(workers, list) and workers else None


def run_reviewers(cfg, state):
    """Old receipts keep their shared list even if the session adds reviewers later."""
    if "reviewers" in state:
        return list(state["reviewers"])
    return run_workers(cfg, state)


def _cached_providers():
    """The usage cache's providers for display: {} when the cache cannot be read."""
    try:
        blob = json.loads((config.STATE / "usage.json").read_text())
        providers = blob.get("providers") if isinstance(blob, dict) else None
        return providers if isinstance(providers, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def executable_models(cfg, providers, workers, now, log=None, *, reviewers=None):
    """(model, provider) pairs that can execute now, in pick order.

    An eligible worker counts when the pick order keeps it, its budget is above zero
    with nothing unknown about it, and no refusal parked its provider until a future
    window.  The tick's availability and the waiting words share this one rule.  `log`
    is told each worker left out because its harness cannot run, as `ready_order` says it.
    """
    from . import usage  # here, not at the top: usage imports staffing
    try:
        order = ready_order(cfg, providers, workers=workers, log=log, role="executor",
                            quiet=True, reviewers=reviewers)
    except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    available = []
    for name in order:
        try:
            provider = config.model(cfg, name)["provider"]
        except config.Error:
            continue
        prov = (providers or {}).get(provider)
        if not isinstance(prov, dict):
            continue
        until = prov.get("exhausted_until")
        if (isinstance(until, (int, float)) and not isinstance(until, bool) and until > now):
            continue  # a refusal parked this provider until its own window; honour the mark
        try:
            budget, reason = usage.model_budget(cfg, name, providers, now)
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if reason is None and budget > 0:
            available.append((name, provider))
    return available


def reviewable_models(cfg, providers, workers, now, executor=None):
    """(model, provider) pairs that can review now, in pick order.

    The reviewer's half of `executable_models`, under the same rule: kept by the
    pick order, budget above zero with nothing unknown about it, provider not
    parked until a future window.  Legality against the saved executor is checked
    too -- a spare the policy forbids beside this executor is no reviewer to
    resume for, and the loop would only park the run again.  Without an executor
    the legality check has nothing to check against, so every available model
    counts.
    """
    from . import usage  # here, not at the top: usage imports staffing
    try:
        order = ready_order(cfg, providers, workers=workers, role="reviewer",
                            quiet=True)
    except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    if executor:
        order = reviewer_order(cfg, executor, order)
    available = []
    for name in order:
        try:
            provider = config.model(cfg, name)["provider"]
        except config.Error:
            continue
        prov = (providers or {}).get(provider)
        if not isinstance(prov, dict):
            continue
        until = prov.get("exhausted_until")
        if (isinstance(until, (int, float)) and not isinstance(until, bool) and until > now):
            continue  # a refusal parked this provider until its own window; honour the mark
        try:
            budget, reason = usage.model_budget(cfg, name, providers, now)
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if reason is None and budget > 0:
            available.append((name, provider))
    return available


def exhausted_waits_for(state, providers, cfg=None, workers=None, now=None):
    """(provider, resets_at, dry) saying which window an `exhausted` run waits on.

    Only a quota run waits on a window at all: anything else, and anything with no
    spent eligible provider, comes back dry=False, and the row keeps the state word.
    Otherwise the answer is the spent eligible provider with the soonest future
    `resets_at` on any of its meters -- (None, None, True) when no spent provider
    carries a future reset, which reads as a window with no known hour.  A run a
    later merged run replaced waits on no window: the tick stood down, marked
    `replaced`, and naming an hour would promise a resume that never comes.
    """
    if state.get("replaced"):
        return None, None, False
    if state.get("state") != "exhausted" or not state.get("quota_dry"):
        return None, None, False
    now = time.time() if now is None else now
    if cfg is None:
        return None, None, True
    if workers is None:
        try:
            workers = run_workers(cfg, state) or config.workers(cfg)
        except (config.Error, KeyError, TypeError, AttributeError):
            return None, None, True
    try:
        names = {config.model(cfg, name)["provider"] for name in workers}
    except (config.Error, KeyError, TypeError, AttributeError):
        return None, None, True
    spent = [provider for provider in names
             if provider not in {prov for _, prov in executable_models(cfg, providers,
                                                                       workers, now)}]
    if not spent:
        return None, None, False
    best, at = None, None
    for provider in spent:
        prov = (providers or {}).get(provider)
        if not isinstance(prov, dict):
            continue
        for meter in prov.get("meters") or []:
            if not isinstance(meter, dict):
                continue
            resets_at = meter.get("resets_at")
            if (isinstance(resets_at, (int, float)) and not isinstance(resets_at, bool)
                    and resets_at > now and (at is None or resets_at < at)):
                best, at = provider, resets_at
    return best, at, True


def waiting_word(state, providers=None, cfg=None, workers=None, now=None):
    """What a parked run's row says instead of the state word.

    `waiting for <harness> login` where a login expired under it, which the tick
    lifts by itself the moment that harness's `auth` verb passes again -- and
    `waiting to resume` once it has passed and only the launch is left.  Otherwise,
    for an `exhausted` run: `waiting for <provider> until HH:MM` for the soonest spent
    window it could use, `waiting for a provider window` when a window is spent but
    none names an hour, and `exhausted` when the run waits on no window at all.  Reads
    the usage cache and the config when they are not handed in; either unreadable
    means none is known.
    """
    if state.get("state") == "waiting_login":
        # the tick found the login back and has not got the resume away yet: what it waits
        # for now is the resume, and naming the login would send him to fix what is fixed
        return ("waiting to resume" if state.get("login_back_at") else
                f"waiting for {state.get('waiting_for') or 'a'} login")
    if providers is None:
        providers = _cached_providers()
    if cfg is None:
        try:
            cfg = config.load()
        except config.Error:
            cfg = None
    provider, at, dry = exhausted_waits_for(state, providers, cfg, workers, now)
    if not dry:
        return "exhausted"
    if provider is None or at is None:
        return "waiting for a provider window"
    try:
        return f"waiting for {provider} until {time.strftime('%H:%M', time.localtime(at))}"
    except (OverflowError, OSError, ValueError):
        return "waiting for a provider window"


def waiting(state, providers=None, cfg=None, workers=None, now=None):
    """The waiting sentence when a run sits out a provider window or an expired login, else "".

    Both resume themselves -- a window refills, a login comes back -- so the listings
    say what the run waits for, never that the owner should reach for its number.
    Anything else, and an exhausted run that waits on no window, reads "".
    """
    from . import gate  # here, not at the top: it reaches run
    if state.get("state") == "queued":
        return gate.slot_note(state)
    if state.get("state") not in ("exhausted", "waiting_login"):
        return ""
    word = waiting_word(state, providers=providers, cfg=cfg, workers=workers, now=now)
    return word if word.startswith("waiting") else ""
