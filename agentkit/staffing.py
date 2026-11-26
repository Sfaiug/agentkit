"""Who executes and who reviews a run.

The models a session marks for each role, drawn per run among them,
the pair a round gets and the refusals when none fits, the hand to the next
executor when one spends its window, and the words a run waiting on a reviewer
or an exhausted provider shows.
"""

import json
import time

from . import config, matrix, record, transitions, turns, update


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
    as one pair (`best_pair`), so tier beats the draw and the pair is always a legal
    one -- a reviewer kept from before can be the very model now executing.  A refused provider
    never gets the work back (that is how a handover becomes a circle); its reviewers
    are considered only when no pair forms without them.  Records the move
    in `executor_history` with the reason (`stalled`, `dry`); an attempt that finds nobody
    records nothing, since the same worker carries on. `dry` is every provider that
    already refused this piece of work.
    Later re-picks follow the normal order; this preference applies only at handover.
    With review on, the executor is one the run's reviewers of another lab can review while
    one of its builders is (`ready_order`'s `reviewed_by`), as at launch.
    """
    off = record.review_off(state)
    if not off:
        # who may review whom reads the run's marks as its own loop does: one the config renamed
        # since launch still builds, reviews and refuses as the model its record holds
        cfg = config.as_launched(cfg, state)
    current = state.get("executor")
    try:
        current_provider = config.model(cfg, current)["provider"] if current else None
    except config.Error:
        current_provider = None
    refused = set(dry)
    if current_provider is not None:
        refused.add(current_provider)
    new = reviewer = None
    draw = state.get("run_id")   # the tick hands over outside the run's own thread
    try:
        providers = collect_usage(cfg)
        reviewers = run_reviewers(cfg, state)
        workers, review_list = config.pair_marks(cfg, run_workers(cfg, state), reviewers)
        order = [n for n in ready_order(cfg, providers, workers, log, reviewers=reviewers,
                                        reviewed_by=None if off else review_list, draw=draw)
                 if n != current and config.model(cfg, n)["provider"] not in refused]
        review_order = [] if off else ready_order(cfg, providers, review_list, role="reviewer",
                                                  draw=draw)
        pair = ((order[0], None) if off and order else
                best_pair(cfg, order, [n for n in review_order
                                      if config.model(cfg, n)["provider"] not in refused]))
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


def ready_order(cfg, providers, workers=None, log=None, writers=None, reviewed_by=None,
                skip=(), **kwargs):
    """`usage.pick_order` over `takers`' list, less the names it leaves out.

    Every pick a run makes -- executor, reviewer, spare, handover, the fixer's -- comes
    through here; `log`, on the one call of a pick that gives a role, says in one line why
    each marked one is left out of the pick returned.  `skip` names those a caller leaves out
    before any rule reads the list, so none of them keeps another out.

    A pick that comes back empty where `takers`' lab rule left names out is made once more of
    those names alone.  The owner, 22 Nov 2026: "Own lab reviews when spent".  So it never
    names one the rule kept, and a caller choosing among it chooses as among any.
    """
    from . import usage  # here, not at the top: usage imports staffing
    role, reviewers = kwargs.get("role", "executor"), kwargs.get("reviewers")
    if skip:
        workers = [name for name in usage.marked(cfg, workers, role, reviewers) if name not in skip]
    marks, skip, by_lab = _takers(cfg, providers, workers, role, reviewers, writers, reviewed_by)
    order = usage.pick_order(cfg, providers, marks, skip=skip, **kwargs)
    if by_lab and not order:
        order = usage.pick_order(cfg, providers, by_lab, **kwargs)
        skip = {name: why for name, why in skip.items() if name not in by_lab}
    if log and skip:
        for name in usage.marked(cfg, marks, role, reviewers):
            if name in skip:
                log(f"skipped {name}: {skip[name]}")
    return order


def takers(cfg, providers, workers=None, role="executor", reviewers=None, writers=None,
           reviewed_by=None):
    """The list a pick for `role` reads, `workers` as given unless a rule below reads it
    (`usage.marked`), and why each name a pick may not take is left out, before any usage rule
    reads the list.

    A worker whose harness is not installed or not logged in, as `providers` say, is left out,
    so a subscription nobody can run keeps no payg provider out; with no `providers` no harness
    is asked.

    A reviewer's pick given `writers`, every model that wrote part of the work, leaves out
    the same way every reviewer sharing a lab with one of them while another that is not
    off, unready or barred shares none (`pair_tier` 0).  The owner, 18 Nov 2026: "same
    provider or model for both roles should still be allowed if only picked, but if multiple
    picked then from different."  So a subscription of a writer's lab keeps no payg reviewer
    of another out.  An executor's pick given `reviewed_by`, the reviewer marks of its run,
    leaves out the same way every executor with no reviewer of them at `pair_tier` 0 that is
    not off, unready or barred, while another has one: the pick is the one a run marking only
    those executors gets.  A pick either rule leaves empty is made again of those it left out
    (`ready_order`).
    """
    return _takers(cfg, providers, workers, role, reviewers, writers, reviewed_by)[:2]


def _takers(cfg, providers, workers=None, role="executor", reviewers=None, writers=None,
            reviewed_by=None):
    """`takers`' two, and the names its lab rule left out: of one reading, so whether the rule
    emptied a pick (`ready_order`) is told by the very call that made the pick's list."""
    from . import usage  # here, not at the top: usage imports staffing
    offered = config.offered(cfg)
    skip = {}
    if getattr(providers, "harnesses", None):
        skip = {name: usage.unready(cfg, name, providers) for name in offered}
        skip = {name: why for name, why in skip.items() if why}
    if role == "reviewer":
        skip.update((name, why) for name in offered if (why := barred_reviewer(cfg, name)))
    writers = known(cfg, writers) if role == "reviewer" else []
    by_lab = []
    if writers or (role == "executor" and reviewed_by is not None):
        # read here, once: `pick_order` then reads only what the other role leaves of it
        workers = usage.marked(cfg, workers, role, reviewers)
        off, (lineup, _) = matrix.off(cfg), matrix.listed()

        def ready(names):
            return [name for name in names
                    if name in offered and name not in skip and name not in off]

        if writers:
            far = [name for name in ready(workers)
                   if all(pair_tier(cfg, writer, name, lineup) == 0 for writer in writers)]
            why = f"a reviewer of another lab than {', '.join(writers)} is marked: {', '.join(far)}"
        else:
            reviews = [name for name in ready(reviewed_by) if not barred_reviewer(cfg, name)]
            far = [name for name in ready(workers)
                   if any(pair_tier(cfg, name, reviewer, lineup) == 0 for reviewer in reviews)]
            why = f"a marked reviewer of another lab can review {', '.join(far)}"
        if far:
            by_lab = [name for name in ready(workers) if name not in far]
            skip.update((name, why) for name in by_lab)
    return workers, skip, by_lab


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
                repo=None, workers=None, reviewers=None, draw=None):
    """Pick each role within its launch list; want_review=False switches review off.  Asked for
    no executor by name, with review on, the executor's pick reads the reviewer named -- or the
    reviewer's list when neither is named -- too (`ready_order`'s `reviewed_by`).  `draw` is
    `usage.pick_order`'s."""
    workers, reviewers = config.role_groups(cfg, workers, reviewers)
    if reviewers is not None:
        refuse_outside_group(cfg, want_review, reviewers, "reviewer")
    exec_list, review_list = workers, reviewers if reviewers is not None else workers
    reviewed_by = None
    if not want_exec and want_review is not False:
        if want_review:
            reviewed_by = [want_review]
        else:
            # the executor's pick weighs the very reviewers the reviewer's pick reads
            exec_list, review_list = config.pair_marks(cfg, workers, reviewers)
            reviewed_by = review_list
    order = ready_order(cfg, providers, exec_list, None if want_exec and want_review else log,
                        quiet=quiet, repo=repo, reviewers=reviewers, reviewed_by=reviewed_by,
                        draw=draw)
    session = config.active_session(cfg) if workers is None else None
    allowed = workers if workers is not None else (session["workers"] if session else None)

    def _where():
        try:
            active = session if workers is None else config.active_session(cfg)
        except config.Error:
            active = None
        return f"session {active['name']!r}" if active else "this run"

    if want_exec:
        config.model(cfg, want_exec)
        # Legacy callers without a bound list retain the default orchestrator on resume.
        admitted = (workers is None and session
                    and session["orchestrator"] == want_exec == cfg["defaults"]["orchestrator"]
                    and (resuming or want_exec in order))
        if allowed is not None and want_exec not in allowed and not admitted:
            raise config.Error(f"{want_exec!r} is not a worker of {_where()}")
        refuse_unready(cfg, providers, want_exec)
    elif not order:
        # a full meter and a provider's refusal leave a worker out alike; the pick says which
        raise turns.QuotaDry("no eligible executor: no worker can execute now; waiting for one")
    executor = want_exec or order[0]
    if want_review is False:
        return executor, None
    if want_review:
        config.model(cfg, want_review)
        if reviewers is None and allowed is not None and want_review not in allowed:
            raise config.Error(f"{want_review!r} is not a worker of {_where()}")
        refuse_unready(cfg, providers, want_review, "reviewer")
        reviewer = want_review
        if want_exec is None:
            # A named reviewer takes the best executor for it: tier first, then the
            # draw, through the same pair choice every automatic pick uses.
            pair = best_pair(cfg, order, [reviewer])
            if pair is not None:
                executor = pair[0]
    else:
        review_order = ready_order(cfg, providers, review_list, role="reviewer", quiet=quiet,
                                   repo=repo, draw=draw)
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
    if want_review is False and ready:
        return None
    if want_review:
        reviews = ([name for name in reviews if name == want_review]
                   if bound_review else [want_review])
    if any(reviewer_order(cfg, name, reviews) for name in ready):
        return None
    if want_review is not False and (barred := barred_refusal(cfg, [want_review] if want_review else review_list)):
        return barred
    why = "; ".join(f"{name}: {reason}" for name, reason in skipped.items() if reason)
    missing = []
    if not ready:
        missing.append(f"workers {', '.join(listed)}")
    if not reviews and want_review is not False:
        missing.append(f"reviewers {', '.join(review_list)}")
    if not missing:  # an unknown explicit name refuses below; name both lists
        missing = [f"workers {', '.join(listed)}",
                   f"reviewers {', '.join(review_list)}"]
    return (f"none of the {' and '.join(missing)} can run here"
            + (f" ({why})" if why else "")
            + "; log in to another harness or add another model to the groups")


def run_refusal(cfg, providers, workers, want_exec=None, want_review=None, reviewers=None):
    """`pair_refusal` over a run's saved role lists, less the names the config no longer
    offers (`config.offered`): the lists outlive the config, and the pick passes over a spare
    retired since (`usage.pick_order`), so a run the others could staff waits for a window.
    No list saved stays None, the config's own selection.  A selection made now goes to
    `pair_refusal` itself, which refuses a model that is gone, so no screen saves one."""
    offered = config.offered(cfg)
    workers, reviewers = (None if names is None else [name for name in names if name in offered]
                          for names in (workers, reviewers))
    return pair_refusal(cfg, providers, workers, want_exec, want_review, reviewers)


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


def known(cfg, names):
    """Those of `names`, one name or a list, the config has a model for.  A writer since
    removed from the config, as a handover's earlier executor, holds no reviewer back: it is
    no model a reviewer could be."""
    def model(name):
        try:
            return config.model(cfg, name)
        except config.Error:
            return None

    return [name for name in ([names] if isinstance(names, str) else names or [])
            if name and model(name)]


def reviewer_order(cfg, writers, order):
    """The order given, by each reviewer's worst `pair_tier` beside the writers.  `writers`
    is the model that wrote the work, or every model that wrote part of it: a PR's
    orchestrator and the fixer its fix was handed to.  A model tends to miss the mistakes it
    makes, so its own review is the last choice -- but only a choice, never a refusal: one
    worker reviews itself."""
    names, (lineup, _) = known(cfg, writers), matrix.listed()
    tiered = [(max((pair_tier(cfg, each, name, lineup) for each in names), default=0), name)
              for name in known(cfg, order)]
    return [name for _, name in sorted(tiered, key=lambda each: each[0])]


def head_writers(state):
    """Every model that wrote part of the head a review judges: a seat's own PR's orchestrator,
    the executor or fixer of the moment, and every model a turn was handed from or to
    (`executor_history`), so none of them is the first choice to review it."""
    names = [state.get("own_orchestrator") if state.get("own_pr") else None, state.get("executor"),
             *(entry.get(key) for entry in state.get("executor_history") or [] for key in ("from", "to"))]
    return list(dict.fromkeys(name for name in names if name))


def review_writers(state):
    """The writers a review's reviewer is picked beside (`ready_order`) where the review begins
    its round, resumes or falls back: its `head_writers`, a seat's own pull request's
    orchestrator among them; none for somebody else's, whose writers ak does not know."""
    return [] if state.get("review_pr") and not state.get("own_pr") else head_writers(state)


def lab(cfg, name, lineup=None):
    """Who makes the configured model `name`: the maker of the row of `lineup`, else of the
    lineup last stored (`matrix.listed`), whose `yours` holds its harness and model, as the
    provider `config.company` names for it.  Where no row holds it, the family word its id opens
    with after any `provider/` prefix (`config.family`, `config.model_id`): the maker of a row
    holding a model whose id opens with the same word, as `config.company` names it, else the
    provider that word's harnesses run on (`_family_provider`), else the word itself; with no
    family word, its provider.  A provider running several makers' models is then as many labs,
    and one maker's models under two providers one lab."""
    entry = config.model(cfg, name)
    mine = {"harness": entry["harness"], "model": entry["model"]}
    rows = matrix.listed()[0] if lineup is None else lineup
    row = next((row for row in rows if mine in row["yours"]), None)
    if row is not None:
        return config.company(cfg, row.get("maker")) or entry["provider"]
    model = config.model_id(entry)
    words = config.families() if model else ()
    word = config.family(model.rsplit("/", 1)[-1], words) if model else None
    if word:
        maker = next((row["maker"] for row in rows if row.get("maker")
                      and any((held := config.model_id(one))
                              and config.family(held.rsplit("/", 1)[-1], words) == word
                              for one in row["yours"])), None)
        return config.company(cfg, maker) or _family_provider(cfg, word) or word
    return entry["provider"]


def _family_provider(cfg, word):
    """The provider the family word `word` is of, as `cfg` tells: the one the models it offers
    (`config.offered`) run on, on the harnesses whose manifest names that word as their family,
    without case.  A model on them that no family word names is of its provider (`lab`), and
    one the word names is then of that lab too, not of one the word alone would be.  None where
    they run on no provider or on several, or theirs runs a harness of another family too:
    `cfg` then names no one maker for the word."""
    runs = set()
    for name in config.offered(cfg):
        entry = cfg["models"][name]
        family = config.manifest(entry["harness"]).get("family")
        if family and isinstance(family, str):
            runs.add((family.lower(), entry["provider"]))
    homes = [provider for family, provider in runs if family == word.lower()]
    alone = len(homes) == 1 and [provider for _, provider in runs].count(homes[0]) == 1
    return homes[0] if alone else None


def pair_tier(cfg, executor, reviewer, lineup=None):
    """This pair's tier, in the owner's order of 21 Oct and 18 Nov
    (tests/test_key_reviewer_other_provider_first.py, tests/test_key_a_lab_is_a_models_maker.py):
    0 a model of another lab (`lab`), 1 another model of the executor's lab, 2 the executor's
    own model.  Own is `same_model`'s: one model id under two providers is two models.
    `lineup` is `lab`'s: a pick weighing several pairs reads it once.

    None when either name is unknown: no pick weighs a pair it cannot name.
    """
    if same_model(cfg, executor, reviewer):
        return 2
    try:
        same = lab(cfg, executor, lineup) == lab(cfg, reviewer, lineup)
    except config.Error:
        return None
    return 1 if same else 0


def best_pair(cfg, executors, reviewers, allow_self=True):
    """The pair every automatic pick takes: tier first, then executor order, then reviewer.

    Both lists are already in pick order (`usage.pick_order`), so the first pair in tier
    order wins: a review by another lab's model beats one by the executor's lab, which beats
    the executor reviewing itself.  A pick that stopped at the first executor would keep a
    worse tier while a better pair is ready.  None when no pair forms -- or only a
    self-review when `allow_self` is off, which a flake waits out.
    """
    best, key, (lineup, _) = None, None, matrix.listed()
    for ei, executor in enumerate(executors or []):
        for ri, reviewer in enumerate(reviewers or []):
            tier = pair_tier(cfg, executor, reviewer, lineup)
            if tier is None or (tier == 2 and not allow_self):
                continue
            found = (tier, ei, ri)
            if key is None or found < key:
                key, best = found, (executor, reviewer)
    return best


def review_pair(state):
    """The recorded review's pair, else the current one. A seat's own PR has no executor,
    so its writer -- the seat's orchestrator -- counts as the executor."""
    evidence = state.get("review") if isinstance(state.get("review"), dict) else {}
    reviewer = evidence.get("reviewer") or state.get("reviewer")
    executor = evidence.get("executor")
    if executor is None:
        executor = state.get("own_orchestrator") if state.get("own_pr") else state.get("executor")
    return executor, reviewer


def self_reviewed(state, cfg=None):
    """Whether this run's review pair is one model. With no config only the same name counts;
    with it, aliases of the same provider and model id count too."""
    executor, reviewer = review_pair(state)
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

    Both roles are re-picked as one pair (`best_pair`), so tier beats the draw: a
    review by another model beats a self-review.  Keeping the current reviewer instead would
    leave the executor only the models it can review -- on 2026-09-22 a Grok refusal kept
    reviewer Muse and pushed execution onto Claude, though executor Muse with reviewer Claude
    was legal.

    `dry` is every provider that has already refused this piece of work, not just the last one:
    a refusal the meters cannot see is still a refusal, and handing the work back to a provider
    that has just turned it down is how a handover becomes a circle.  `workers`, when given,
    is the run's bound list: nothing outside it is ever picked.  `allow_self` False keeps a
    flaky provider's handover off a self-review pair: the flake usually answers after a wait,
    so only a provider that cannot run the work settles for one.  With review on, the
    executor is one the run's reviewers of another lab can review while one of its builders is
    (`ready_order`'s `reviewed_by`), as at launch.  Neither role's pick reads a name on a
    provider in `dry`.  `log` hears the executor's pick.
    """
    workers, reviewers = config.role_groups(cfg, workers, reviewers)
    workers, review_list = config.pair_marks(cfg, workers, reviewers)

    def taking(names):
        return [n for n in known(cfg, names) if config.model(cfg, n)["provider"] not in dry]

    # before the picks read them: a refused subscription below pace keeps no payg one out
    workers, review_list = taking(workers), taking(review_list)
    order = ready_order(cfg, providers, workers, log, repo=repo, reviewers=reviewers,
                        reviewed_by=None if reviewer is False else review_list)
    if reviewer is False and order:
        return order[0], None
    review_order = ready_order(cfg, providers, review_list, role="reviewer", repo=repo)
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
        new, reviewer = next_executor(lp.cfg, providers, dry,
                                      False if record.review_off(lp.state) else lp.reviewer, lp.log,
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
    if isinstance(workers, list) and (workers or "reviewers" in state):
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


def refusal_backoff(state, now):
    """The executor a short refusal keeps out of the run's picks until the moment it named
    (`turns.RanDry.remember`): the tick's that resumes it and the resumed run's alike."""
    retry = state.get("refusal_retry")
    model, at = (retry.get("model"), retry.get("at")) if isinstance(retry, dict) else (None, None)
    return (model,) if isinstance(model, str) and isinstance(at, (int, float)) and now < at else ()


def resume_needs_executor(state):
    # Landing invalidates review before its fixer runs. That pending review is not
    # proof the executor finished: a refused rebase/final fixer still needs its fuel.
    return state.get("step") == "executor" or not (
        transitions.exhausted_wait(state) == "reviewer" or state.get("review_pr")
        or state.get("review_pending"))


def resume_models(cfg, providers, state, log=None, *, repo=None, workers=None, skip=None):
    """The pair a resume can actually run, shared by its admission and the tick.

    Keep the saved executor while eligible, otherwise hand over as mid-round. A
    refusal with no replacement parks before taking a slot, never on the saved model.
    `skip` names executors it leaves out, by default the one a refusal keeps out now.
    """
    from . import usage
    skip = refusal_backoff(state, time.time()) if skip is None else skip
    draw = state.get("run_id")   # the tick and a resume's admission pick outside its thread
    bound, reviewers = config.role_groups(cfg, run_workers(cfg, state), state.get("reviewers"))
    workers = bound if bound is not None else workers
    if record.review_off(state):
        executor = state.get("executor")
        if executor in skip or (executor and (usage.unready(cfg, executor, providers)
                                               or usage.model_exhausted(cfg, executor, providers)[0])):
            executor = None
        group = ([*workers, executor] if workers is not None and state.get("own_pr")
                 and executor == state.get("own_orchestrator") else workers)
        return pick_models(cfg, providers, executor, False, log, resuming=True,
                           quiet=True, repo=repo, workers=group, draw=draw)
    # a resume that needs no executor keeps it, so the reviewer is picked beside its writers
    needs = resume_needs_executor(state)
    # the pick anew weighs the very reviewers the reviewer's pick reads
    exec_list, review_list = config.pair_marks(cfg, workers, reviewers)
    review_order = ready_order(cfg, providers, review_list, role="reviewer", quiet=True, repo=repo,
                               writers=None if needs else review_writers(state), draw=draw)
    executor, reviewer = state.get("executor"), state.get("reviewer")
    if not needs:
        order = reviewer_order(cfg, executor, review_order) if executor else review_order
        if order:
            return executor, reviewer if reviewer in order else order[0]
        raise turns.QuotaDry("no eligible reviewer; waiting for review")
    # one the config no longer defines (`config.as_launched`) is none to keep, and is refused by
    # that name below unless the run waits
    kept = (known(cfg, executor) and executor not in skip
            and not usage.model_exhausted(cfg, executor, providers)[0]
            and not usage.unready(cfg, executor, providers))

    def executors(log=None, reviewed_by=None):
        return ready_order(cfg, providers, exec_list, log, quiet=True, repo=repo,
                           reviewers=reviewers, reviewed_by=reviewed_by, skip=skip, draw=draw)

    # a pair picked anew takes its executor as a launch picking both roles does (`pick_models`)
    order = executors(log, None if kept else review_list)
    if kept:
        if reviewer not in reviewer_order(cfg, executor, review_order):
            reviewer = None
        group, writer = workers, state.get("own_orchestrator") if state.get("own_pr") else None
        if workers is not None and executor == writer:
            # A seat's own PR is fixed by the model that wrote it (`run.review_pr`), which no
            # worker list holds: the pick takes it as one, and who may review stays as it was.
            group, reviewers = [*workers, writer], reviewers if reviewers is not None else workers
        return pick_models(cfg, providers, executor, reviewer, log, resuming=True, quiet=True,
                           repo=repo, workers=group, reviewers=reviewers, draw=draw)
    pair = best_pair(cfg, order, review_order)
    # a pair only that pick leaves out is waited for: its executor can run here, so nothing is
    # asked of the saved one; else, as before that pick, one the config dropped is refused by
    # name, and one whose harness cannot run where no pair is left
    if executor and (pair is not None or not best_pair(cfg, executors(), review_order)):
        if executor not in skip:
            config.model(cfg, executor)
        if pair is None:
            refuse_unready(cfg, providers, executor)
    if pair is not None:
        return pair
    offered = config.offered(cfg)   # a spare retired since launch has no meter to name
    reasons = [why for name in (workers if workers is not None else config.workers(cfg))
               if name in offered and (why := usage.model_exhausted(cfg, name, providers)[1])]
    raise turns.QuotaDry("nothing is left to execute with a legal reviewer"
                         + (": " + "; ".join(dict.fromkeys(reasons)) if reasons else ""))


def _cached_providers():
    """The usage cache's providers for display: {} when the cache cannot be read."""
    try:
        blob = json.loads((config.STATE / "usage.json").read_text())
        providers = blob.get("providers") if isinstance(blob, dict) else None
        return providers if isinstance(providers, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _budgeted(cfg, providers, order, reads, now):
    """(model, provider) pairs of `order` whose selected worker login has a positive known
    budget, read off the same login `pick_order` picked it on (`reads`) so exhaustion and
    budget never split across two logins."""
    from . import usage  # here, not at the top: usage imports staffing
    available = []
    for name in order:
        try:
            provider = config.model(cfg, name)["provider"]
        except config.Error:
            continue
        if not isinstance((providers or {}).get(provider), dict):
            continue
        try:
            read = reads[name] if name in reads else usage._worker_reading(cfg, name, providers)
            if name not in reads and usage.model_exhausted(cfg, name, read)[0]:
                continue
            budget, reason = usage.model_budget(cfg, name, read, now)
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if reason is None and budget > 0:
            available.append((name, provider))
    return available


def executable_models(cfg, providers, workers, now, log=None, *, reviewers=None):
    """(model, provider) pairs that can execute now, in pick order.

    An eligible worker counts when the pick order keeps it, which no refusal parked until a
    future window keeps (`usage.model_exhausted`), and its budget is above zero with nothing
    unknown about it.  The waiting words use this conservative estimate of capacity.  `log`
    is told each worker left out because its harness cannot run, as `ready_order` says it.
    """
    try:
        order = ready_order(cfg, providers, workers=workers, log=log, role="executor",
                            quiet=True, reviewers=reviewers)
    except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    return _budgeted(cfg, providers, order, getattr(order, "reads", {}), now)


def reviewable_models(cfg, providers, workers, now, executor=None, writers=None):
    """(model, provider) pairs that can review now, in pick order.

    The reviewer's half of `executable_models`, under the same rule: kept by the
    pick order, budget above zero with nothing unknown about it.  Legality against the
    saved executor is checked too -- a spare the policy forbids beside this executor is
    no reviewer to resume for, and the loop would only park the run again.  Without an
    executor the legality check has nothing to check against, so every available model
    counts.  `writers` narrow the pick as `ready_order`'s do.
    """
    try:
        order = ready_order(cfg, providers, workers=workers, role="reviewer",
                            quiet=True, writers=writers)
    except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    reads = getattr(order, "reads", {})
    if executor:
        order = reviewer_order(cfg, executor, order)
    return _budgeted(cfg, providers, order, reads, now)


def exhausted_waits_for(state, providers, cfg=None, workers=None, now=None):
    """(provider, resets_at, dry) saying which window an `exhausted` run waits on.

    Only a quota run waits on a window at all: anything else, and anything with no
    spent eligible provider, comes back dry=False, and the row keeps the state word.
    Otherwise the answer is the spent eligible provider with the soonest future
    `resets_at` on any of its meters -- (None, None, True) when no spent provider
    carries a future reset, which reads as a window with no known hour.  A run a
    later merged run replaced waits on no window: the tick stood down, marked
    `replaced`, and naming an hour would promise a resume that never comes.  A run
    parked for its review waits on a reviewer the tick picks when it resumes: naming
    one here would be a second pick, which can part from the tick's, so it names none.
    """
    if state.get("replaced"):
        return None, None, False
    if state.get("state") != "exhausted" or not state.get("quota_dry"):
        return None, None, False
    if not resume_needs_executor(state):
        return None, None, True
    now = time.time() if now is None else now
    if cfg is None:
        return None, None, True
    try:
        # the run's marks as its own resume reads them: one gone from the config since launch
        # is a worker still where its record holds it, and waits on no window where it is not
        cfg = config.as_launched(cfg, state)
        if workers is None:
            workers = run_workers(cfg, state) or config.workers(cfg)
        offered = config.offered(cfg)
        names = {config.model(cfg, name)["provider"] for name in workers if name in offered}
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
