"""Every current model on the boards, a row per release and effort with the installed harnesses'
models that are it (`lineup`), answered per role on quality and cost (`answer`), using
`quality.pick`.  Only the models of your
companies you left on are compared (`compared`) or used (`off`): the owner, 5 Nov 2026.  Under
the boards `ak models` prints each role's models by the tasks they did with the team now
(own.py); `--json` carries beside them ak's own run numbers per configured model, the effort its
runs recorded and role, with their count, which never rank (`live`).
Attribution: Source: Artificial Analysis (artificialanalysis.ai); arena.ai.
"""

import contextlib
import decimal
import fcntl
import fractions
import functools
import json
import math
import re
import sys
import time

from . import catalog, command_help, config, quality, rates, record, terminal
from .boards import PREFIX, collect, effort_rank

# the config's word for each role ak answers: `config.ROLE_EFFORTS` keys its efforts by these
CONFIG_ROLES = {"orchestrate": "orchestrator", "execute": "executor", "review": "reviewer"}


def cache_path():
    return config.STATE / "matrix.json"


@contextlib.contextmanager
def _locked():
    """One writer of `matrix.json`, the matrix as last computed, at a time: `matrix.lock` held
    while its `.tmp` is written and moved in, so two writers never share the `.tmp`."""
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    with cache_path().with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _held():
    """`matrix.json` as it is, {} where it is not or unreadable."""
    try:
        return json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return {}


def _write(cache):
    tmp = cache_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(cache_path())


def present():
    """Every harness present to run a turn, the ones whose models the matrix rows."""
    return sorted({name for name, _ in config.manifests() if config.harness_present(name)})


def config_key(cfg):
    """What of the config the matrix is computed from: a change here recomputes it."""
    return sorted([name, cfg["models"][name]["harness"], cfg["models"][name]["model"],
                   *(config.role_effort(cfg["models"][name], role) for role in config.ROLE_EFFORTS)]
                  for name in config.offered(cfg))


def normal(text):
    """A model's name as every board and config spells it alike: its letters and digits."""
    return re.sub(r"[^a-z0-9]", "", text.rsplit("/", 1)[-1].lower())


def found(index, model):
    """A board's rows for one model: under its exact name, else under a board's name naming no
    version of its own that `model` extends with one (`Acme Pro` for `acme-pro-1.0`, never
    `Acme 5` for `acme-5-5`), else under the one board name that is `model` with a qualifier in
    brackets (`Acme 5 (Default Fallback)`; two such names stand for nothing), else under each
    board name that adds a version or date to a `model` naming none (`Acme Flash 1017` for
    `acme-flash`, `lineup` taking only one release), else the same matches without a trailing
    `-free` pricing tier; none where the board has nothing for it or `model` holds no letter or
    digit, which names nothing (`catalog._names`)."""
    wanted = normal(model)
    if not wanted:
        return []
    if wanted in index:
        return index[wanted]
    stems = [stem for stem in index if stem and not stem[-1].isdigit()
             and wanted.startswith(stem) and wanted[len(stem):].isdigit()]
    if stems:
        return index[max(stems, key=len)]
    qualified = [stem for stem, hits in index.items()
                 if normal(re.sub(r"\([^()]*\)", "", hits[0]["model"])) == wanted]
    if len(qualified) == 1:
        return index[qualified[0]]
    extended = [hit for stem, hits in index.items() for hit in hits
                if not wanted[-1:].isdigit() and stem.startswith(wanted)
                and stem[len(wanted):].isdigit()]
    if extended:
        return extended
    if model.endswith("-free"):
        # Free is a pricing tier, so use the underlying model's board rows.
        return found(index, model.removesuffix("-free"))
    return []


def _release_index(releases):
    index = {}
    for release in releases:
        # the name first: `found` reads the first hit's for a bracketed qualifier; either may lack
        for name in filter(None, (release["name"], release["slug"])):
            index.setdefault(normal(name), []).append({"model": name, "release": release})
    return index


def lineup(boards, offers):
    """A row per current release (`catalog.current`) and effort, `name` as ak says it
    (config.release_label), of its slug where that of its name is empty, and `board_name` as
    the board does, `maker` as the board names it, "" where it names none, as `companies` in
    the config writes one, with its `values` as the catalog joins them and `yours`: each model of
    `offers` ({harness: config.catalog(harness)}) that `found` matches to this release alone,
    as {"harness", "model"}, at each effort it lists and at a row naming no effort, which is
    the model however it is run, or at the release's default where it lists none but `none`."""
    releases = catalog.current(boards)
    index = _release_index(releases)
    yours = {}
    for harness, models in offers.items():
        for model in models:
            hits = {hit["release"]["slug"]: hit["release"] for hit in found(index, model["id"])}
            if len(hits) != 1:
                continue
            [release] = hits.values()
            words = (None, *model["efforts"]) if set(model["efforts"]) - {"none"} else None
            for effort in release["efforts"]:
                if effort["effort"] in words if words else effort["default"]:
                    yours.setdefault((release["slug"], effort["effort"]), []).append(
                        {"harness": harness, "model": model["id"]})
    return [{"release": release["slug"],
             "name": (config.release_label(release["name"] or "")
                      or config.release_label(release["slug"])),
             "board_name": release["name"], "maker": release["maker"] or "",
             "effort": effort["effort"], "values": effort["values"],
             "yours": yours.get((release["slug"], effort["effort"]), [])}
            for release in releases for effort in release["efforts"]]


def _task_usage(cfg):
    from . import spend     # here, not at the top: spend reads this module as it loads
    return spend.roles(cfg)


def _costs(rated, lineup, cfg, logins, shares):
    """Prices the rows of each role of `rated` ({role: `quality.rated`'s rows}) and returns the
    one unit every role is in: `board_dollars`, the boards' price of their own task, before any
    run of yours measured a row of `lineup`; else `money`, dollars a task, where a provider your
    runs measured has a price a month; else `share`, points of a week.  A provider's price is
    the mean of its `logins`' that have one, else its usual login's (`usage.price`).  A week
    of a plan is 100 points, or 12/52 of its price, else of the mean price of the measured
    providers with one.  Each offered model `found` as one release alone measures its rows at
    the points of its provider's week and the listed dollars its runs took (`shares`), a point
    a hundredth of that week.  A measured row costs what the first such model measured; any
    other, its board price times what a board dollar of every measurement of its role, rated or
    not, on its provider costs where one is, else times their listed dollars a board dollar at
    its provider's rate; a role with none, as an orchestrator that launched no task, takes every
    role's.  A provider's rate, what a listed dollar takes of its plans, is the mean of its
    `logins`' weeks over what each holds ({provider: [(price, listed dollars)]}), as any of them
    may pay for the next task; one with none takes the mean of the others'.  Each row keeps its
    `board_cost`, the `runs` its measured cost is the mean of (0 for none), `cost_rule` says
    which rule priced it, `provider` the one it is priced on, whose runs measured it, else its
    own, None on its board price alone, and `points` the points of a week of that provider it
    takes, None where none of its logins' weeks holds some."""
    # ak's own runs price a role and never rate it: asked on 5 Nov 2026 what their runs should
    # decide, the owner answered "Costs only", as quality comes from the boards.
    from . import usage
    rows = {(row["release"], row["effort"]): row for row in lineup}
    # matched as `lineup` matched, on the name the board spells, not the one ak says; a lineup
    # an earlier build stored has only its `name`, the board's, and the models screen reads it
    # until it computes it again
    index = _release_index({row["release"]: {"slug": row["release"],
                                             "name": row.get("board_name", row.get("name"))}
                            for row in lineup}.values())
    providers = {}  # each release's provider: its first offered model's
    measured = {}   # (role, release, effort): [(provider, points, runs, listed)], a model's each
    for name in config.offered(cfg):
        entry = cfg["models"][name]
        hits = {hit["release"]["slug"] for hit in found(index, entry["model"])}
        if len(hits) != 1:
            continue
        [release] = hits
        providers.setdefault(release, entry["provider"])
        for effort, roles in shares.get(name, {}).items():
            for role, word in CONFIG_ROLES.items():
                if (release, effort) in rows and roles.get(word) is not None:
                    measured.setdefault((role, release, effort), []).append(
                        (entry["provider"], *roles[word]))
    for each in rated.values():
        for row in each:
            row.update(board_cost=row["cost"], cost_rule="board", runs=0, points=None,
                       provider=None)
    if not measured:
        return "board_dollars"
    # a share is of its logins' weeks, any of which pays the next task: so their mean, never
    # the price of the login a past task ran on, the owner's choice of 21 Nov 2026.  Of the
    # logins whose week is fitted (`logins`) alone, so price and week are the same logins': one
    # with a price and no week yet, on a plan no fitted login shares the name of, joins once it
    # has one.  The owner, 22 Nov 2026: "Leave it".
    def price(provider):
        held = [one for one, _ in logins.get(provider, ()) if one is not None]
        return sum(held) / len(held) if held else usage.price(cfg, provider)
    # every provider your runs measured, though no row the boards rate is its measured model
    prices = {provider: price(provider) for provider in {
        cfg["models"][name]["provider"] for name in config.offered(cfg) if shares.get(name)}}
    known = [price for price in prices.values() if price is not None]
    mean = sum(known) / len(known) if known else None

    def week(price):    # a plan's week in the unit, 12/52 of the month a price pays for
        return 100 if mean is None else (mean if price is None else price) * 12 / 52

    def cost(provider, points):
        return week(prices[provider]) / 100 * points

    def rate(provider, week):   # what a listed dollar takes of its logins' plans, in `week`'s unit
        each = [week(price) / listed for price, listed in logins[provider]]
        return sum(each) / len(each)
    rates = {provider: (rate(provider, week), rate(provider, lambda _: 100))
             for provider in logins if logins[provider]}    # {provider: (in the unit, in points)}
    either = sum(one for one, _ in rates.values()) / len(rates) if rates else None
    # (role, provider, cost, board dollars, points, listed dollars)
    samples = [(role, provider, cost(provider, points), board, points, listed)
               for (role, release, effort), each in measured.items()
               for provider, points, _, listed in each
               for board in [rows[release, effort]["values"].get(quality.COSTS[role])]
               if board is not None and board > 0]

    def per_board_dollar(some, what):   # the cost, with `what` 4 the points, 5 the listed dollars
        return sum(one[what] for one in some) / sum(one[3] for one in some)
    for role, each in rated.items():
        # its own once a row of it is measured, though no board prices that row: other roles'
        # runs say nothing of a role its own runs measure
        pool = ([one for one in samples if one[0] == role]
                if any(key[0] == role for key in measured) else samples)
        for row in each:
            mine = measured.get((role, row["release"], row["effort"]))
            if mine:
                provider, points, runs, _ = mine[0]
                row.update(cost=cost(provider, points), cost_rule="measured", runs=runs,
                           points=points, provider=provider)
                continue
            provider = providers.get(row["release"]) or config.company(cfg, row.get("maker"))
            own = [one for one in pool if one[1] == provider]
            if own:     # its provider's runs paid a board dollar at what its own plans take
                factors = per_board_dollar(own, 2), per_board_dollar(own, 4)
            elif pool:  # any other provider's listed dollars take what they take of its plans
                factors = [None if one is None else per_board_dollar(pool, 5) * one
                           for one in rates.get(provider, (either, None))]
            else:
                factors = None, None
            # Without board dollars or a measured conversion, no same-unit estimate exists.
            priced, points = (None if one is None or row["board_cost"] is None
                              else row["board_cost"] * one for one in factors)
            row.update(cost_rule="provider" if own else "global", cost=priced, points=points,
                       provider=provider)
    return "share" if mean is None else "money"


def answer(lineup, compared=None, *, cfg=None, task_usage=None):
    """Per role, `rated`: `quality.rated` over every row of `lineup`, so a row's quality never
    changes with what is compared; then over the rows of the releases in `compared` (slugs, None
    for every one), `best`: the row of best quality, `pick` by role, `front`: those with a cost,
    best first, each better than every cheaper one, a row of yours than every cheaper one of
    yours, as one no harness of yours runs is no reason to leave it out; `take`: the same rule
    over yours; and `choices` over those with a cost, `others` and `whys` over every one
    (`_choices`), the choices being rows a take can take (`takes`).  Keep the pick and take
    visible even if rows outside their eligible pool beat them.  `unrated`: the names of the
    releases compared it rates no row of, as `p` lists them (`company_order`).  Every role's
    costs are in one unit (`_costs`), off `task_usage`, (logins, shares) as `spend.roles`
    measures them.  `limits`: each choice's price (`_limits`)."""
    measures = task_usage if task_usage is not None else _task_usage(cfg) if cfg else ({}, {})
    cfg = cfg or {"models": {}, "providers": {}}
    every = {role: quality.rated(lineup, role) for role in quality.ROLES}
    unit = _costs(every, lineup, cfg, *measures)
    order = company_order(cfg, lineup)
    releases = {row["release"]: row["name"] for row in sorted(
        lineup, key=lambda row: order.index(row["maker"]))
        if compared is None or row["release"] in compared}
    out = {}
    for role, rated in every.items():
        them = [row for row in rated if row["release"] in releases]
        scored = {row["release"] for row in them}
        best = max(them, key=lambda row: row["quality"], default=None)
        priced = sorted((row for row in them if row["cost"] is not None),
                        key=lambda row: (row["cost"], -row["quality"]))
        pick = quality.pick(them, role)
        take = quality.pick([row for row in them if row["yours"]], role)
        front = sorted((row for n, row in enumerate(priced) if row is pick or row is take or all(
            cheaper["quality"] < row["quality"] for cheaper in priced[:n]
            if cheaper["yours"] or not row["yours"])), key=lambda row: -row["quality"])
        choices, others, whys = _choices(priced, [row for row in them if row["cost"] is None],
                                         {id(row) for row in priced if takes(cfg, row)})
        out[role] = {"cost_unit": unit, "rated": rated, "best": best, "pick": pick,
                     "front": front, "take": take, "choices": choices, "others": others,
                     "whys": whys, "limits": _limits(choices, priced),
                     "unrated": [name for slug, name in releases.items() if slug not in scored]}
    return out


def _limits(choices, priced):
    """{id: limit} of `choices`, the price a take of each stops at (menu.keep_price), the
    owner's design of 5 Nov 2026: round_price up to the cheapest of `priced` both dearer and
    better, which the next choice is; None on the best, which stays the best whatever it costs."""
    return {id(row): None if row is choices[-1] else round_price(row["cost"], min(
        one["cost"] for one in priced if one["cost"] > row["cost"]
        and one["quality"] > row["quality"])) for row in choices}


def round_price(cost, dearer):
    """The geometric middle of `cost` and `dearer`, at the fewest significant figures that land
    from `cost` up to, not including, `dearer`: 0.12 and 0.80 keep 0.3, 1 and 3 keep 2, 4.2 and
    5 keep 4.6."""
    middle = math.sqrt(cost * dearer)
    return next((one for figures in range(1, 18)
                 if cost <= (one := float(f"{middle:.{figures}g}")) < dearer), cost)


def runner(cfg, row):
    """The configured model a take of `row` takes: the first of config.offered running it."""
    return next((name for name in config.offered(cfg) if {
        "harness": cfg["models"][name]["harness"], "model": cfg["models"][name]["model"]}
        in row["yours"]), None)


def takes(cfg, row):
    """What a take of `row` takes, the one rule of the rows `answer` chooses among: the
    configured model running it (`runner`); else, the owner's word of 5 Nov 2026, "Let the
    question of the model exists from my choices be my concern", the model a take sets up
    (menu.set_up) beside one of yours, as a seat's harness running a model no entry runs adds
    one beside the entry it leaves (watch._taken_in): the first of its `yours` on a harness a
    configured model runs on, on the provider its id names (`<provider>/<model>`) where that
    harness runs any provider it logs in to (config.provider_hosts), {"harness", "model"} with
    the first such model's `provider`, and its `mode` where it has one.  None for neither: a
    model ak holds no login for, on a harness running none of yours or listed by none, stays
    shaded `not set up` until its company is added on `c`, never set up on a login ak has
    not seen; the owner, 17 Nov 2026, asked whether one should: "Stay shaded"."""
    name = runner(cfg, row)
    if name or not row["yours"]:
        return name
    hosts, offered = config.provider_hosts(), [cfg["models"][one] for one in config.offered(cfg)]
    for one in row["yours"]:
        named = one["model"].partition("/")[0] if one["harness"] in hosts else None
        beside = next((entry for entry in offered if entry["harness"] == one["harness"]
                       and named in (None, entry["provider"])), None)
        if beside:
            return {**one, **{key: beside[key] for key in ("provider", "mode") if key in beside}}
    return None


# The models screen's choices, the owner, 5 Nov 2026: none further below the best than WINDOW
# points, each APART above the one before, PLACES of them at most.
WINDOW, APART, PLACES = 10, 1, 5


def _above(row, other):
    """The quality points `row` is above `other`, to a millionth, for the `WINDOW` and `APART`
    lines only: a rating's roundoff never moves a row across one, as 90 is 10 under 100, never
    10.00000000000001, while a row a millionth better still ranks above."""
    return round(row["quality"] - other["quality"], 6)


def _choices(priced, costless, runs):
    """Of `priced`, cheapest first and an equal cost better first, and `costless`, the rows with
    no cost, (`choices`, `others`, `whys`), `runs` holding the ids of the rows a take can take
    (`takes`): `choices` are theirs (`_chosen`), so a better row none can take moves none.
    `others`: of each release with no choice its best row with a cost, a cheaper one on a tie,
    else its best row, best first, those with a cost before those with none: every release
    compared the role rates is among the choices or them, as `p` turns it on (the owner, 5 Nov
    2026).
    `whys`: by its id, each row no choice's (`_why`), which a role using it draws too
    (menu.models_bars), kept beside the rows as what is compared never changes a row; one no
    take can take has the why it would have were it takeable, the same rule over them and it."""
    def chosen(row=None):     # the rule over the rows `runs` holds and `row`
        return _chosen([one for one in priced if id(one) in runs or one is row])
    choices, front = chosen()
    whys = {id(row): _why(row, *((choices, front) if id(row) in runs else chosen(row)))
            for row in (*priced, *costless) if not any(one is row for one in choices)}

    def rank(row):            # a release's top: its best row with a cost, else its best
        return row["cost"] is not None, row["quality"]
    picked, tops = {row["release"] for row in choices}, {}
    for row in (*priced, *costless):
        top = tops.get(row["release"])
        if row["release"] not in picked and (top is None or rank(row) > rank(top)):
            tops[row["release"]] = row
    # a cost of None is never weighed against one: rows with a cost and with none sort apart
    return choices, sorted(tops.values(), key=lambda row: (
        row["cost"] is None, -row["quality"], row["cost"])), whys


def _chosen(priced):
    """Of `priced`, cheapest first, (choices, front).  Its front holds each row better than
    every cheaper one, the best last.  Its choices: the front's rows within `WINDOW` of the
    best, cheapest first, each kept when `APART` above the last kept, the best taking the place
    of one less than that below it; the costliest `PLACES` of them."""
    front = []
    for row in priced:
        if not front or row["quality"] > front[-1]["quality"]:
            front.append(row)
    kept = []
    for row in front:
        if _above(front[-1], row) > WINDOW:
            continue
        if kept and _above(row, kept[-1]) < APART:
            if row is front[-1]:
                kept[-1] = row
        else:
            kept.append(row)
    return kept[-PLACES:], front


def _why(row, choices, front):
    """(`why`, `by`) of `row` beside `choices` and `front` (`_chosen`): where it has no cost,
    so is never a bar or a step of ← or → (menu.stands), by None, `no cost` where no board
    prices it, else `not converted`, as your runs and plans give its board price no cost
    (`_costs`); `not set up`, by None, among the choices, as a row no take can take is
    where it would be one (`_choices`); off the front, `beaten` by the cheapest choice, else
    row of the front, as good and no dearer; on it, `far below`, by None, more than `WINDOW`
    under the best; else `close` to the nearest choice, less than `APART` from it; else `no
    room`, by None: `APART` or more under every choice, as the costliest `PLACES` leave it."""
    if row["cost"] is None:
        return "no cost" if row["board_cost"] is None else "not converted", None
    if any(one is row for one in choices):
        return "not set up", None
    if not any(one is row for one in front):
        return "beaten", next(one for one in (*choices, *front)
                              if one["quality"] >= row["quality"] and one["cost"] <= row["cost"])
    if _above(front[-1], row) > WINDOW:
        return "far below", None
    # the nearer by the qualities as they are: rounded (`_above`), two choices a hair unlike in
    # distance tie, and the cheaper would be named for the nearer
    near = min(choices, key=lambda one: abs(one["quality"] - row["quality"]))
    return ("close", near) if abs(_above(near, row)) < APART else ("no room", None)


def companies(cfg, lineup):
    """The makers you have, as the boards name them: `companies` in the config, else the makers
    of the releases the `[defaults]` orchestrator, workers and reviewers run, the rows of
    `lineup` whose `yours` holds that model's harness and model."""
    if cfg.get("companies") is not None:
        return set(cfg["companies"])
    defaults = cfg["defaults"]
    runs = {(cfg["models"][name]["harness"], cfg["models"][name]["model"])
            for name in (defaults["orchestrator"], *defaults["workers"],
                         *defaults.get("reviewers", ())) if name in cfg["models"]}
    return {row["maker"] for row in lineup for one in row["yours"]
            if (one["harness"], one["model"]) in runs}


def company_order(cfg, lineup):
    """Every maker in the order `p` lists your companies (`companies`) in: `companies` in the
    config as it lists them, then the makers of `lineup` as it orders them, strongest first."""
    return list(dict.fromkeys([*cfg.get("companies", ()), *(row["maker"] for row in lineup)]))


@functools.lru_cache(maxsize=1)
def _listed(text):
    held = json.loads(text).get("matrix") or {}
    # an earlier build stored a maker the boards leave unnamed as null, not "" (`lineup`)
    lineup = [{**row, "maker": row["maker"] or ""} for row in held.get("lineup") or []]
    return (lineup, {row["release"]: row["maker"] for role in quality.ROLES
                     for row in quality.rated(lineup, role)}), held.get("fetched_at")


def listed():
    """The lineup last stored and its listed releases, {slug: maker}: each a role rates a row of
    (`answer`'s `rated`), rated once per stored lineup, so a release without scores is never
    listed; ([], {}) where nobody stored one."""
    return dated()[0]


def dated():
    """`listed`'s pair and the `fetched_at` stored with it (`stored`), of one read: a refresh
    between two reads would date one lineup by another's boards."""
    try:
        return _listed(cache_path().read_text())
    except (OSError, ValueError):
        return ([], {}), None


def ours(cfg, reading=None):
    """The listed releases of your companies (`companies`): what the models screen counts.  Off
    `reading`, `listed`'s pair, where the caller read one: a refresh between two reads would mix
    two lineups."""
    lineup, found = reading or listed()
    makers = companies(cfg, lineup)
    return {slug for slug, maker in found.items() if maker in makers}


def compared(cfg, reading=None):
    """The releases on, the only ones the models screen and `ak models` compare: those of
    `ours` (off `reading` alike) whose slug `models_off` in the config does not hold.  A
    company's next release is on by itself."""
    return ours(cfg, reading) - set(cfg.get("models_off") or ())


def off(cfg):
    """The configured models ak never uses: each running a listed release that is not on, or
    one `models_off` holds however the boards list it, as its owner said of a model off: "ak
    never uses it".  The release a model runs is the one whose rows of the lineup last stored
    hold its harness and model in their `yours`, scored or not; else, once no
    row holds it, a slug of `models_off` its own id (`config.model_id`) names (`found`).  A
    model running an unlisted release nobody turned off, or none, is not the list's to turn
    off: so one off through its company alone is on again once the boards rate its release no
    more, and one whose id names no slug of `models_off` once they list it no more, where a
    role still marks it.  The owner, 21 Nov 2026, left it so ("Drop it"): three designs
    remembering what was off failed nine reviews on a config edit beside a refresh, and no
    model of theirs off is marked.  The picks leave them out (usage.pick_order, usage.unready,
    orch.in_order), and a turn or a seat named on one outright is refused (`refuse_off`)."""
    lineup, makers = listed()
    turned = set(cfg.get("models_off") or ())
    if not makers and not turned:
        return set()
    gone = set(makers) - ours(cfg, (lineup, makers)) | turned
    named = _release_index({"slug": slug, "name": None} for slug in turned)

    def is_off(entry):
        mine = {"harness": entry["harness"], "model": entry.get("model")}
        held = [row["release"] for row in lineup if mine in row["yours"]]
        own = config.model_id(entry)
        return held[0] in gone if held else bool(own and found(named, own))
    return {name for name in config.offered(cfg) if is_off(cfg["models"][name])}


OFF = "off in the model list"     # why a pick leaves out a model of `off`


def refuse_off(cfg, name):
    """Refuse a turn or a seat on `name` while it is off: every turn (worker.call) and every
    seat's command (orch.command) ask this first, so no named, saved or configured model gets
    around the picks."""
    if name in off(cfg):
        raise config.Error(f"{name} is {OFF}: turn it on with `companies` or `models_off` "
                           "in config.toml")


# the run's column holding the effort the role ran it at (None where it was not recorded); a
# review's effort is its review row's
EFFORT_OF = {"orchestrate": "own_orchestrator_effort", "execute": "executor_effort"}


def live(cfg, now=None):
    """ak's own numbers per configured model, the effort it ran at and role, which never rank.
    Off the history's runs that ended with a verdict of the work (`record.JUDGED`): of the runs
    it executed, how many and the share merged in round 1 (`history.merged`); of the pull
    requests its seat wrote (the row's `own_orchestrator`), how many and the share merged in
    round 1.  Of the runs it finished a review of, by its harness and model id, whatever became
    of them since, how many and the share it let through in round 1 (`history.reviewed_runs`).
    {(name, effort): {role: {"runs", "round_1"} or None}}: a key per effort the model's runs
    recorded, the strongest first, effort None for runs that recorded none and for a model that
    ran nothing."""
    from . import history     # here, not at the top: the boards and the table need no database
    now = time.time() if now is None else now
    rows = [row for row in history.ended_runs(0, now) if row.get("final_state") in record.JUDGED]
    first = {row["run_id"] for row in rows
             if (row.get("rounds_used") or 0) <= 1 and history.merged(row)}
    found = {}
    for name in config.offered(cfg):
        counts = {}     # {effort: {role: (runs, of them in round 1)}}
        for role, column in (("orchestrate", "own_orchestrator"), ("execute", "executor")):
            for row in rows:
                if row.get(column) == name:
                    mine = counts.setdefault(row.get(EFFORT_OF[role]) or None, {})
                    runs, in_first = mine.get(role, (0, 0))
                    mine[role] = (runs + 1, in_first + (row["run_id"] in first))
        entry = cfg["models"][name]
        for effort, reviewed in history.reviewed_runs(entry["harness"], entry["model"]).items():
            counts.setdefault(effort or None, {})["review"] = reviewed
        for effort in sorted(counts, key=lambda word: (word is None, -effort_rank(word))) or [None]:
            found[name, effort] = {
                role: share(*counts.get(effort, {}).get(role, (0, 0))) for role in quality.ROLES}
    return found


def share(runs, in_round_1):
    """`{"runs", "round_1"}`: how many runs, and the share of them in round 1; None with none."""
    return {"runs": runs, "round_1": round(100 * in_round_1 / runs)} if runs else None


def stored():
    """The matrix as last computed, {"computed_at", "config", "harnesses", "build", "lineup",
    "fetched_at"} (`lineup` over the boards and harnesses it read, the newest board's
    `fetched_at`), or {}."""
    return _held().get("matrix") or {}


def needed():
    """The columns `quality` reads, by board, for `collect`: each role's measures and the cost
    of its task, the index and what each measure's error cannot be had without.  A board whose
    cached rows carry none of one is read again by a new build, since its reader changed."""
    columns = {quality.INTEL, *quality.COSTS.values()} | {
        name for role in quality.ROLES.values() for column, *_ in role
        for name in (column, *quality.reads(column))}
    return {board: {column for column in columns if column.split(".")[0] == prefix}
            for board, prefix in PREFIX.items()}


def refresh(cfg, *, refresh=False, now=None):
    """The boards (`collect`) and the matrix computed from them and the config, written to
    `state/matrix.json` so every pick reads one computed truth; computed again
    only once a board answered anew, the config's models changed, the harnesses installed are
    not the ones it rowed or ak's own build is not the one that computed it (a matching rule
    that landed holds at the next reading, not a day later), since the harness catalogs it asks
    take time.  Asked as the models screen opens and by `ak models`, never the tick: the owner
    wants the assessment as a feature opened, not a process running all day (22 Oct 2026).
    The matrix is the lineup (`lineup`), so the models screen reads it and asks no catalog.
    Returns (boards, the lineup)."""
    from . import update        # here, not at the top: update reaches this module through orch
    now = time.time() if now is None else now
    harnesses, build = present(), update.agentkit_build()
    boards = collect(refresh=refresh, now=now, needs=needed(), build=build)
    held = stored()
    fetched = max((board.get("fetched_at") or 0 for board in boards.values()), default=0)
    if (held.get("lineup") is not None and held.get("computed_at", -1) >= fetched
            and held.get("config") == config_key(cfg) and held.get("harnesses") == harnesses
            and held.get("build") == build):
        return boards, held["lineup"]
    offers = {harness: config.catalog(harness, cfg) for harness in harnesses}
    rows = lineup(boards, offers)
    with _locked():
        _write({"matrix": {"computed_at": now, "config": config_key(cfg), "harnesses": harnesses,
                           "build": build, "lineup": rows, "fetched_at": fetched}})
    return boards, rows


def row_of(rows, entry, effort):
    """The row of `rows` the model entry `entry` runs at `effort`, as `lineup` holds it: at that
    effort, else at none, the model however it is run, else, run at `none`, its one row."""
    held = [row for row in rows
            if {"harness": entry["harness"], "model": entry["model"]} in row["yours"]]
    return next((row for want in (effort, None) for row in held if row["effort"] == want),
                held[0] if effort == "none" and len(held) == 1 else None)


def uses(cfg, record, found):
    """{role: (model, effort, row)} seat `record`, or [defaults], uses off `found` (`answer`): its
    orchestrator, named even once the config drops it, else its first mark the config holds, as
    a pick for no run takes them (each run draws its own: `usage.pick_order`), None for none;
    the effort the seat runs it at; and its row (`row_of`)."""
    cfg, workers = config.at_efforts(cfg, record), record["workers"]
    used = {}
    for role, names in (("orchestrate", [record["orchestrator"]]), ("execute", workers),
                        ("review", record.get("reviewers", workers))):
        name = next((one for one in names if one in cfg["models"]), next(iter(names), None))
        entry = cfg["models"].get(name)
        effort = entry and config.role_effort(entry, CONFIG_ROLES[role])
        used[role] = name, effort, entry and row_of(found[role]["rated"], entry, effort)
    return used


def team_now(cfg, record):
    """{role (ledger.ROLES): [(name, effort)]}: the models seat `record`, or [defaults], holds
    for each role in the order held, each at the effort a run launched now records
    (`config.run_marks`), None for none (`config.launched_effort`); off no board, unlike `uses`."""
    marks = config.run_marks(cfg, record)
    return {role: [(name, config.launched_effort(marks, name, role)) for name in names]
            for role, names in (("orchestrator", [record["orchestrator"]]),
                                ("executor", record["workers"]),
                                ("reviewer", record.get("reviewers", record["workers"])))}


def notes(row, said):
    """What `ak models --json` notes beside a row of `said`, `answer`'s for a role."""
    missing = sum(one["how"] == "missing" for one in row["measures"].values())
    return [word for word, true in (
        ("pick", row is said["pick"]),
        (f"{missing} missing", missing), ("no harness", not row["yours"])) if true]


def _printed(value):
    """Exact Fraction `value` rounded once to six significant digits as a Decimal, as a float holds
    none below its own smallest, and one past a float's largest as that largest."""
    if value > sys.float_info.max:
        return sys.float_info.max
    return decimal.Context(prec=6).divide(value.numerator, value.denominator)


def by_plan(days, fits=None):
    """`ak models --json`'s `week_meters`, {provider: {plan: {"points", "tokens", "rates"}}}:
    `days`, `week_meters.days`'s, summed by plan, the points to six significant digits, and the
    rates fitted from them (`rates.fitted`), each rounded once from the fit's exact value to six
    significant digits (`_printed`)."""
    fits, plans = rates.fitted(days) if fits is None else fits, {}
    for provider, plan, points, tokens in days:
        summed = plans.setdefault(provider, {}).setdefault(plan, [0, {}])
        summed[0] += points
        for model, count in tokens.items():
            summed[1][model] = summed[1].get(model, 0) + count
    return {provider: {plan: {"points": float(f"{float(points):.6g}"), "tokens": tokens,
                              "rates": {model: _printed(rate)
                                        for model, rate in fits[provider, plan].items()}}
                       for plan, (points, tokens) in found.items()}
            for provider, found in plans.items()}


def dumped(value, at="\n"):
    """`value` as JSON, as `json.dumps(value, indent=2)` writes it but each Decimal as its
    digits and each Fraction rounded once to six significant digits (`_printed`), which json
    writes of neither; `at` begins each of its lines but the first."""
    inner = at + "  "
    if isinstance(value, fractions.Fraction):
        value = _printed(value)
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, dict) and value:
        return "{" + ",".join(
            f"{inner}{json.dumps(key if isinstance(key, str) else json.dumps(key))}: "
            f"{dumped(item, inner)}" for key, item in value.items()) + at + "}"
    if isinstance(value, (list, tuple)) and value:
        return "[" + ",".join(inner + dumped(item, inner) for item in value) + at + "]"
    return json.dumps(value)


def main(argv):
    if command_help.show("models", argv):
        return 0
    flags = set(argv)
    if flags - {"--json", "--refresh"}:
        raise config.Error(f"usage: ak models [--json] [--refresh]  (got {argv!r})")
    from . import menu      # here, not at the top: the menu reaches this module as it loads
    cfg = config.load()
    _, rows = refresh(cfg, refresh="--refresh" in flags)
    marked = compared(cfg)
    logins, shares = _task_usage(cfg)
    found = answer(rows, marked, cfg=cfg, task_usage=(logins, shares))
    seat = config.active_session(cfg) or cfg["defaults"]     # the seat it runs in, else new seats
    # here, not at the top: the boards and the screen need no database
    from . import ledger, own, week_meters
    if "--json" in flags:
        until = time.time()
        since = until - ledger.WINDOW
        meters = week_meters.shared_weeks(cfg, since, until)
        days = week_meters.days(cfg, since, until, meters=meters)
        fits = rates.fitted(days)
        by_run = week_meters.run_usage(cfg, since, until, fits, meters=meters)
        by_seat = week_meters.seat_usage(cfg, since, until, fits, meters=meters)
        runs = ledger.counted(by_run, by_seat, until=until)
        mine = own.by_role(runs["teams"], team_now(cfg, seat))

        def drawn(row, said):
            return {**{key: row[key] for key in ("release", "name", "effort", "quality", "se",
                                                 "cost", "board_cost", "cost_rule")},
                    "notes": notes(row, said)}
        sys.stdout.write(dumped({**{role: {
            "best": said["best"] and said["best"]["quality"], "cost_unit": said["cost_unit"],
            **{key: [drawn(row, said) for row in said[key]] for key in ("front", "choices")},
            "others": [{**drawn(row, said), "why": why, "by": by and {
                key: by[key] for key in ("name", "effort")}}
                for row in said["others"] for why, by in [said["whys"][id(row)]]]}
            for role, said in found.items()},
            # `name @ effort`, the name alone for no effort, a name's own @ doubled so that a
            # model named `acme @ max` never takes the key of acme's runs at max
            "live": {name.replace("@", "@@") + (f" @ {effort}" if effort else ""): roles
                     for (name, effort), roles in live(cfg).items()},
            "task_usage": {name: {effort: {role: share for role, (share, *_) in did.items()}
                                  for effort, did in efforts.items()}
                           for name, efforts in shares.items()},
            "runs": runs, "own": mine,
            "week_meters": by_plan(days, fits)}))
        print()
        return 0
    mine = own.by_role(ledger.counted()["teams"], team_now(cfg, seat))
    used, unit = uses(cfg, seat, found), menu.models_unit()     # the screen's, as it was left
    body, _ = menu.models_body(menu.models_said(cfg, found, used, unit), unit)
    bars = [line for role in found
            for line in menu.models_bars(found[role], role, used[role][2], used[role][2], unit)]
    print("\n".join([*body, *bars, "", *menu.models_read(marked, len(ours(cfg)),
                                                   stored().get("fetched_at")),
                      "", *own.lines(mine, cfg, terminal.layout_width())]))
    return 0
