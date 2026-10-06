"""config.toml loading, model resolution, and every agentkit path."""

from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import tomllib
from pathlib import Path

from . import host

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home() / ".agentkit"
RUNS, WT, STATE, SECRETS, TMP, ENV, WORK = (
    HOME / n for n in ("runs", "wt", "state", "secrets", "tmp", "env", "work"))


# Python calls __getattr__ for config.JOBS: it follows HOME wherever a test or a checkout
# moves it, so sandboxing HOME keeps job receipts out of the owner's real ~/.agentkit.
# Anything patching config.JOBS explicitly keeps working, since it shadows this fallback.
def __getattr__(name):
    if name == "JOBS":
        return HOME / "jobs"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


JOB_DIR_ENV = "AGENTKIT_JOB_DIR"  # the `ak run --bg` job child this receipt belongs to
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
HARNESS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")   # a harness name is one path component


RUN_DIR_ENV = "AGENTKIT_RUN_DIR"
ADAPTER_DIR_ENV = "AGENTKIT_ADAPTER_DIR"   # adapters/ elsewhere: the offline smoke checks
SESSION_ENV = "AGENTKIT_SESSION"
RULEBOOK_DIR_ENV = "AGENTKIT_RULEBOOK_DIR"  # a dry run's: where rulebook.py writes instead of STATE
SEAT_REPO_ENV = "AGENTKIT_SEAT_REPO"      # a new seat's project, for rulebook.py: no record yet
ACCOUNT_ENV = "AGENTKIT_ACCOUNT"           # which of a provider's `accounts` an adapter call is for
DEFAULT_ACCOUNT = "default"                # ... the login it has when it lists none: the empty name
KEPT_LOGINS = "kept-logins.json"           # under STATE: the logins `− remove` left on disk
UNATTENDED_ENV = "AGENTKIT_UNATTENDED"   # set below a run loop: what it starts is machinery
CODE = Path.home() / "code"                # where the checkouts live, and where a new seat opens
RENAME_HOPS = 8                            # how many renames a session name is followed through
DEFAULT_MODEL = "default"                  # config.toml: the harness runs its own model, no -m
SESSION_STALE = 7 * 86400                  # a record whose session has been gone this long goes
RUN_DEFAULTS = {"max_runs": 0}
CONFIG_NAME = "config.toml"                # the one config file, under HOME: never in the checkout
DEFAULT_CONFIG_NAME = "config.default.toml"   # ... whose shipped default install.sh copies there
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")   # the effort words for a
                               # harness whose adapter manifest names none of its own
CATALOG_TTL = 60               # seconds a harness's model list is reused before it is asked again
CATALOG_NOW = 0.05             # seconds catalog_now waits on catalog() before the answer it has


class Error(Exception):
    """A user-facing error: printed as `ak: <message>` with no traceback."""


def max_runs():
    """Positive host count ceiling; zero means no count cap (or no gates for AK_MAX_RUNS)."""
    override = os.environ.get("AK_MAX_RUNS")
    if override is not None:
        if not override.isascii() or not override.isdigit():
            raise Error("AK_MAX_RUNS must be a non-negative integer (0 disables the cap for tests)")
        return int(override)
    return _count_setting("max_runs")


def max_gates():
    """Pinned heavy-suite turns, or None when the config leaves the count derived.

    An explicit `max_gates` in the home config file pins the host-wide count, 0
    still meaning no cap; a missing file or a missing key means the count is
    derived from the slice's live headroom, never a shipped number.
    """
    path = HOME / CONFIG_NAME
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise Error(f"{path}: {exc}") from exc
    if "max_gates" not in data:
        return None
    value = data["max_gates"]
    if type(value) is not int or value < 0:
        raise Error(f"{path}: max_gates must be a non-negative integer")
    return value


def _count_setting(key):
    """A non-negative integer at the top of the home config file, or the shipped default."""
    path = HOME / CONFIG_NAME
    try:
        with path.open("rb") as fh:
            value = tomllib.load(fh).get(key, RUN_DEFAULTS[key])
    except FileNotFoundError:
        return RUN_DEFAULTS[key]
    except (OSError, ValueError) as exc:
        raise Error(f"{path}: {exc}") from exc
    if type(value) is not int or value < 0:
        raise Error(f"{path}: {key} must be a non-negative integer")
    return value


def _resource_setting(key, environment, default):
    """Read one host gate setting without requiring the model tables in config.toml."""
    override = os.environ.get(environment)
    if override is not None:
        try:
            value = float(override) if "." in override else int(override)
        except ValueError as exc:
            raise Error(f"{environment} must be a non-negative number") from exc
        if isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise Error(f"{environment} must be a non-negative number")
        return value
    path = HOME / CONFIG_NAME
    try:
        with path.open("rb") as fh:
            value = tomllib.load(fh).get(key, default)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise Error(f"{path}: {exc}") from exc
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise Error(f"{path}: {key} must be a non-negative number")
    return value


def min_free_mb(mem_total_mb=None):
    """Minimum MemAvailable, defaulting to the larger of 3072 MB and 20% of RAM."""
    if mem_total_mb is None:
        mem_total_mb = host.memory_mb("MemTotal") or 0
    default = max(3072, mem_total_mb * 0.20)
    return _resource_setting("min_free_mb", "AK_MIN_FREE_MB", default)


def max_load(cpus=None):
    """Maximum one-minute load, defaulting to the host's processor count."""
    cpus = host.cpu_count() if cpus is None else cpus
    default = max(1, cpus or 1)
    return _resource_setting("max_load", "AK_MAX_LOAD", default)


def max_load_is_set():
    """True when the owner pinned the host load gate, in the config or the environment.

    Pinned, the old load check still decides admission, with its old meaning;
    unset, the slice's own CPU pressure gates instead and the default above
    goes unread. A corrupt config answers False here and raises where the
    gate itself reads it, as before.
    """
    if os.environ.get("AK_MAX_LOAD") is not None:
        return True
    try:
        with (HOME / CONFIG_NAME).open("rb") as fh:
            return "max_load" in tomllib.load(fh)
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return False


def run_memory_max_mb():
    """The per-run memory cap in MiB, or None when the config leaves it unset.

    Unset is not zero.  The caller then takes 40% of the slice ceiling, or
    4 GB where there is no ceiling to read.  A present value is that cap,
    whatever the ceiling is:
    one leaking run has to be stoppable without waiting to see how large the
    host is.  A bool would pass an ``int`` check, so the type has to be ``int``
    exactly.
    """
    path = HOME / CONFIG_NAME
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise Error(f"{path}: {exc}") from exc
    if "run_memory_max_mb" not in data:
        return None
    value = data["run_memory_max_mb"]
    if type(value) is not int or value <= 0:
        raise Error(f"{path}: run_memory_max_mb must be a positive integer")
    return value


def json_pages(text):
    """Decode gh api --paginate's consecutive JSON documents, without newer gh flags."""
    decoder, pages = json.JSONDecoder(), []
    rest = text.lstrip()
    while rest:
        page, end = decoder.raw_decode(rest)
        pages.append(page)
        rest = rest[end:].lstrip()
    if not pages:
        raise ValueError("gh printed no JSON pages")
    return pages


def child_env():
    """The environment for anything a run spawns.

    AGENTKIT_RUN_DIR marks the `ak run --bg` child.  Left in place it reaches every model
    call and done-when command, where a nested `ak run` adopts this run's directory,
    worktree and task file instead of making its own.  IDLE_COMPACT_STATE marks the
    seat's idle-compact state file; left in place a spawned worker's Stop hook would
    overwrite the seat's file with the worker's own context numbers.  A harness's own
    seat variables and AK_RUN_SCOPE go the same way and for the same reason: they are the
    launch's, not its children's -- see `seat_env_names`.  So does AGENTKIT_ACCOUNT: it names
    the login one adapter call is for, and a turn on one account starts nothing that should
    run on it unasked.
    """
    dropped = {RUN_DIR_ENV, "AK_RUN_SCOPE", "IDLE_COMPACT_STATE", ACCOUNT_ENV, *seat_env_names()}
    return {k: v for k, v in os.environ.items() if k not in dropped}


def harness_binary(name):
    """The binary the way its adapter finds it: PATH first, its own bin dir as fallback.

    ~/.opencode/bin and ~/.grok/bin are on no fresh shell's PATH, so a lookup by PATH
    alone misses a working install -- the adapter would reinstall over it, and `ak
    update` would call it missing.  The fallback answers only where PATH has none: an
    explicit placement first on PATH -- a test fake, a version manager, /usr/local --
    keeps its precedence and is never shadowed by the installer's own dir.  Every
    adapter does the same check in shell; this is the same answer in Python.  An
    absolute path answers itself when it is executable, and anything unanswered is "",
    the way shutil.which says it with None.
    """
    if "/" in name:
        path = Path(name)
        return name if path.is_file() and os.access(path, os.X_OK) else ""
    found = shutil.which(name)
    if found:
        return found
    home = Path.home()
    grok_bin = Path(os.environ.get("GROK_BIN_DIR") or home / ".grok/bin")
    for directory in (home / ".opencode/bin", grok_bin,
                      home / ".local/bin", home / ".npm-global/bin"):
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return ""


def seatless_env():
    """child_env() without the seat's name: nothing below the loop speaks for a seat.

    The loop process keeps $AGENTKIT_SESSION, because that is where a run's `launched_session`
    comes from at launch.  A model call and a done-when command below it do not: an `ak run` or
    a smoke suite they start would otherwise count as launched from the seat that launched the
    loop -- reported to it, typed into it, and counted in its row.

    $AGENTKIT_UNATTENDED says what the missing name cannot.  A run launched by hand has no seat
    either, but it has the terminal it was started from, and the menu still offers it; a run
    started below another run has neither, so it is machinery and belongs on no menu at all.
    """
    return {**{k: v for k, v in child_env().items() if k != SESSION_ENV}, UNATTENDED_ENV: "1"}


def unattended():
    """Whether this process was started below a run loop rather than by a person."""
    return bool(os.environ.get(UNATTENDED_ENV))


def repo_env(repo):
    """The KEY=value pairs of ~/.agentkit/env/<repo-basename>.env, or {} if there is none.

    A repo's test secrets live on the machine, never in the repo.  A line the file gets wrong
    ends the run: a typo that silently dropped one variable would surface as a test failure the
    executor cannot fix, so it is reported here, by line number and without its value.
    """
    path = ENV / f"{Path(repo).name}.env"
    if not path.exists():
        return {}
    try:
        text = path.read_text()
    except OSError as exc:
        raise Error(f"cannot read {path}: {exc}")
    env = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not KEY.match(key):
            raise Error(f"{path}:{n}: not a KEY=value line")
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key] = value
    return env


def _read_toml(path):
    """Parse one TOML file, or None when there is no such file."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Error(f"cannot read {path}: {exc}")
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise Error(f"{path}: {exc}")


def load():
    """The config: ~/.agentkit/config.toml, else the default shipped in the checkout.

    install.sh copies that default to the home file once and never again, so a config the
    owner has edited survives every later install, and a checkout nobody has installed from
    still reads -- silently, because there is nothing to fix.

    It is the same file max_runs() reads, and an install from before the models moved into it
    left only that key there.  A file that configures no models at all is not a broken config:
    the shipped default answers for the models, and the home file still answers for max_runs.

    Every model is offered as orchestrator and as worker; `[defaults]` names the orchestrator
    and the workers a new seat starts with, the last created seat's (remember_defaults): a
    model removed since is passed over here, and stays in the file.  A file from before it said
    that with two tier lists, and reads as what they meant outside a session: the first of A
    orchestrating for B without it.  Nothing writes it back until the config is next saved,
    which then writes `[defaults]` and the top-level `pace_margin` in their place.
    """
    tables = ("defaults", "tiers", "models", "providers")
    path = HOME / CONFIG_NAME
    cfg = _read_toml(path)
    if cfg is None or not any(table in cfg for table in tables):
        path = REPO / DEFAULT_CONFIG_NAME
        cfg = _read_toml(path)
        if cfg is None:
            raise Error(f"missing {path}")
    for key in ("models", "providers"):
        if not isinstance(cfg.get(key), dict):
            raise Error(f"{path}: missing [{key}] table")
    names = offered(cfg)
    if not names:
        raise Error(f"{path}: no [models.*] entry names a provider with a [providers.*] table")
    tiers = cfg.pop("tiers", None)
    if isinstance(tiers, dict):
        if "pace_margin" in tiers:
            cfg.setdefault("pace_margin", tiers["pace_margin"])
        first, rest = tiers.get("A"), tiers.get("B")
        if "defaults" not in cfg and isinstance(first, list) and first and isinstance(rest, list):
            cfg["defaults"] = {"orchestrator": first[0],
                               "workers": [name for name in rest if name != first[0]]}
    defaults = cfg.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        raise Error(f"{path}: [defaults] must be a table")
    if not isinstance(defaults.setdefault("orchestrator", names[0]), str):
        raise Error(f"{path}: [defaults].orchestrator must be a model name "
                    f"(got {defaults['orchestrator']!r})")
    written = "workers" in defaults        # an empty group nobody wrote is no choice of one
    workers = defaults.setdefault("workers", [])
    if (not isinstance(workers, list) or any(not isinstance(name, str) for name in workers)
            or len(set(workers)) != len(workers)):
        raise Error(f"{path}: [defaults].workers must list distinct model names "
                    f"(got {workers!r})")
    if "reviewers" in defaults:
        reviewers = defaults["reviewers"]
        if (not isinstance(reviewers, list) or not reviewers
                or any(not isinstance(name, str) for name in reviewers)
                or len(set(reviewers)) != len(reviewers)):
            raise Error(f"{path}: [defaults].reviewers must list distinct model names "
                        f"(got {reviewers!r})")
    # Only a creation writes [defaults], so one may name a model removed since: passed over
    # here, as a default nobody named is, and the first model takes a place it empties, so a
    # seat can still start with Enter.
    _fall_back(defaults, names, written)
    for name, entry in cfg["providers"].items():
        listed = entry.get("accounts", []) if isinstance(entry, dict) else []
        # each name is a path component: the adapters keep that account's login under it
        if (not isinstance(listed, list)
                or not all(isinstance(one, str) and HARNESS.fullmatch(one) for one in listed)
                or len(set(listed)) != len(listed)):
            raise Error(f"{path}: [providers.{name}].accounts must list distinct names of "
                        f"letters, digits, '.', '_' and '-' (got {listed!r})")
    return cfg


def offered(cfg):
    """Every model the config offers, each under its provider: each one can orchestrate, and
    each can work.

    A `[models.*]` entry is offered once its provider has a `[providers.*]` table; one whose
    provider has none stays in the file and out of every choice.  Every list of models reads
    this order -- a provider where its first model is in the file, its models in file order
    under it -- so a model added last still sits with its provider's others on every screen.
    """
    names = [name for name, entry in cfg["models"].items()
             if isinstance(entry, dict) and isinstance(entry.get("provider"), str)
             and entry["provider"] in cfg["providers"]]
    providers = dict.fromkeys(cfg["models"][name]["provider"] for name in names)
    return [name for provider in providers for name in names
            if cfg["models"][name]["provider"] == provider]


def remove_provider(cfg, name):
    """Take one provider out of `cfg`: its table and its models.

    [defaults] stays as the last creation left it, and load() passes over the models gone from
    it.  The last provider cannot go, since a config with no model has nothing to start a seat
    on.  Its usage row goes with its table: the menu and `ak usage` list, and probe, only the
    providers the config has.  The caller saves.
    """
    if name not in cfg["providers"]:
        raise Error(f"no provider {name!r}; the config has {', '.join(cfg['providers'])}")
    left = [model for model in offered(cfg) if cfg["models"][model]["provider"] != name]
    if not left:
        raise Error(f"{name} is the last provider with a model; add another before removing it")
    del cfg["providers"][name]
    for model in [model for model, entry in cfg["models"].items()
                  if isinstance(entry, dict) and entry.get("provider") == name]:
        del cfg["models"][model]
    return cfg


def remove_model(cfg, name):
    """Take one model out of `cfg`, the way remove_provider takes one provider's: [defaults]
    stays, and the last model cannot go.  Its provider stays, settings and all, so another of
    its models can be added; a `usage_model` naming it goes, and that usage call falls to the
    provider's first model.  The caller saves.
    """
    left = [model for model in offered(cfg) if model != name]
    if not left:
        raise Error(f"{name} is the last model; add another before removing it")
    provider = cfg["providers"][cfg["models"].pop(name)["provider"]]
    if provider.get("usage_model") == name:
        del provider["usage_model"]
    return cfg


def provider_harnesses(cfg, provider):
    """The harnesses `provider` runs on, for the `c` screen's `add a model`: the ones its
    models in `cfg` run on, then the ones the shipped default runs it on, each once.  A
    provider neither names a harness for is offered none, never a guess."""
    models = shipped().get("models")
    entries = [*cfg["models"].values(), *(models.values() if isinstance(models, dict) else ())]
    return list(dict.fromkeys(entry["harness"] for entry in entries
                              if isinstance(entry, dict) and entry.get("provider") == provider
                              and isinstance(entry.get("harness"), str)))


def shipped():
    """The shipped config.default.toml as it parses, {} when it does not: the providers the
    `c` screen's `+ add` offers, each added as it is here."""
    try:
        return _read_toml(REPO / DEFAULT_CONFIG_NAME) or {}
    except Error:
        return {}


def _fall_back(defaults, left, written=True):
    """Keep defaults to models `left`; executors written empty beside reviewers stay empty,
    and a `[defaults]` that never named its executors falls back to the first model."""
    if defaults.get("orchestrator") not in left:
        defaults["orchestrator"] = left[0]
    named = defaults.get("workers") or []
    defaults["workers"] = [model for model in named if model in left] or (
        [] if not named and written and "reviewers" in defaults else [left[0]])
    if "reviewers" in defaults:
        defaults["reviewers"] = [model for model in defaults["reviewers"]
                                if model in left] or [left[0]]


_CATALOGS = {}


def catalog_table(harness):
    """The `[catalog]` table of that harness's manifest, as catalog() returns a list.

    Keyed by model id, in file order, each with its `label` and its `efforts` strongest last;
    written from the harness's own docs or `--help` for one that cannot list its models.
    `efforts = ["none"]` is a model that runs at no effort, and is configured `effort = "none"`;
    an entry that names no efforts is a model whose efforts nobody has said.
    """
    table = manifest(harness).get("catalog")
    if not isinstance(table, dict):
        return []
    return [{"id": model, "label": str(entry.get("label") or model),
             "efforts": [word for word in entry.get("efforts") or [] if isinstance(word, str)]}
            for model, entry in table.items() if isinstance(entry, dict)]


def catalog(harness):
    """The models that harness can run: dicts of `id`, `label` and `efforts`, strongest last.

    `adapters/<h>.sh models` answers, one `id<TAB>label<TAB>efforts` line per model: live where
    the harness lists its own, else -- and when that listing fails or outlasts ten seconds --
    from the `[catalog]` table of its manifest.  `none` is the one effort of a model that runs
    at no effort; an empty efforts field, a model whose efforts its harness does not say.  An
    adapter that fails, says nothing usable, or is still
    going after fifteen seconds leaves that table too.  Cached a minute per harness, because
    a live listing asks the harness's server.
    """
    now = time.monotonic()
    cached = _CATALOGS.get(harness)
    if cached and now - cached[0] < CATALOG_TTL:
        return cached[1]
    try:
        proc = subprocess.run([str(adapter(harness)), "models"], capture_output=True, timeout=15,
                              stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                              env=child_env())
        out = proc.stdout if proc.returncode == 0 else ""
    except (Error, OSError, subprocess.TimeoutExpired):
        out = ""
    models = [{"id": fields[0], "label": fields[1] or fields[0], "efforts": fields[2].split()}
              for fields in (line.split("\t") for line in out.splitlines())
              if len(fields) == 3 and fields[0]] or catalog_table(harness)
    _CATALOGS[harness] = (now, models)
    return models


_ASKING, _ANSWERED = {}, {}      # catalog_now's: the thread asking catalog(), what it last said


def catalog_now(harness):
    """catalog() for a key that is drawn at once: its answer if it comes within CATALOG_NOW
    seconds, as a cached one does, else the last one it gave, else the manifest's table.

    A listing asks the harness itself and can take fifteen seconds, so it goes on in the
    background and the next key reads it.  Only a step on the `c` screen reads this way;
    `ak doctor`, a model id's step and `add a model` wait for catalog() as before.
    """
    asking = _ASKING.get(harness)
    if asking is None or not asking.is_alive():
        asking = _ASKING[harness] = threading.Thread(target=_ask_catalog, args=(harness,),
                                                     daemon=True)
        asking.start()
    asking.join(CATALOG_NOW)
    return _ANSWERED[harness] if harness in _ANSWERED else catalog_table(harness)


def _ask_catalog(harness):
    try:
        _ANSWERED[harness] = catalog(harness)
    except Error:
        pass            # catalog_now falls back to the table, which says the same error


def efforts(harness, model=None, now=False):
    """That harness's effort words, in the order the `c` screen cycles them -- or that model's.

    Given a model its catalog says the efforts of, those are the answer -- `none` alone for one
    that runs at no effort.  Otherwise `[effort] levels` in its adapter manifest is the
    vocabulary; a harness that names none -- a fourth one, or the echo fixture -- takes the
    fixed list, which holds every word the shipped defaults use.  `now` reads the catalog
    through catalog_now, for a key that cannot wait on a listing.
    """
    if model is not None:
        for entry in (catalog_now if now else catalog)(harness):
            if entry["id"] == model and entry["efforts"]:
                return list(entry["efforts"])
    block = manifest(harness).get("effort")
    levels = block.get("levels") if isinstance(block, dict) else None
    if isinstance(levels, list) and levels and all(
            isinstance(word, str) and word for word in levels):
        return list(levels)
    return list(EFFORTS)


def _toml_key(key):
    if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value):
    # bool before int: isinstance(True, int) is true and TOML spells them differently.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise Error(f"cannot write {value!r} to {CONFIG_NAME}: not a TOML number")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{_toml_key(key)} = {_toml_value(item)}"
                          for key, item in value.items())
        return "{" + inner + "}"
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    raise Error(f"cannot write {value!r} to {CONFIG_NAME}: not a TOML value")


def _ordered(items, first):
    """Those pairs in a canonical key order, then whatever else the dict held, in place."""
    led = [pair for key in first for pair in items if pair[0] == key]
    return led + [pair for pair in items if pair[0] not in set(first)]


SAVE_HEADER = ("# agentkit's config, written by the menu's `c` screen. It is rewritten whole on "
               "every change,",
               "# so a comment left here would not survive it; unknown keys are kept as they are.")
_TOP_ORDER = ("max_runs", "max_gates", "min_free_mb", "max_load", "run_memory_max_mb", "pace_margin")
_DEFAULTS_ORDER = ("orchestrator", "workers", "reviewers")
_MODEL_ORDER = ("harness", "model", "effort", "provider", "meter")
_PROVIDER_ORDER = ("mode", "usage_model", "usage_effort")


def _dump_table(path, value, chunks):
    """One TOML table and whatever it holds, appended to chunks; unknown shapes included.

    Tables the schema knows are ordered canonically by the caller; anything else -- a new
    top-level table, a nested table, an array of tables -- is written in place, so a setting
    this writer never heard of still survives a menu edit with its value unchanged.
    """
    if isinstance(value, dict):
        head = "[" + ".".join(_toml_key(part) for part in path) + "]"
        pairs = [(key, item) for key, item in value.items() if not isinstance(item, dict)
                 and not (isinstance(item, list) and any(isinstance(bit, dict) for bit in item))]
        chunks.append([head] + [f"{_toml_key(key)} = {_toml_value(item)}" for key, item in pairs])
        for key, item in value.items():
            if isinstance(item, dict):
                _dump_table([*path, key], item, chunks)
            elif isinstance(item, list) and any(isinstance(bit, dict) for bit in item):
                for bit in item:
                    if not isinstance(bit, dict):
                        raise Error(f"cannot write {CONFIG_NAME}: [{key}] mixes tables and values")
                    head = "[[" + ".".join(_toml_key(part) for part in [*path, key]) + "]]"
                    chunks.append([head] + [f"{_toml_key(k)} = {_toml_value(v)}"
                                            for k, v in bit.items()])
    elif isinstance(value, list) and all(isinstance(bit, dict) for bit in value):
        for bit in value:
            head = "[[" + ".".join(_toml_key(part) for part in path) + "]]"
            chunks.append([head] + [f"{_toml_key(k)} = {_toml_value(v)}"
                                    for k, v in bit.items()])
    else:
        raise Error(f"cannot write {CONFIG_NAME}: [{path[-1]}] is not a table")


def dump(cfg):
    """This config as TOML text: the known tables canonically ordered, the rest in place."""
    for table in ("defaults", "models", "providers"):
        if table in cfg and not isinstance(cfg[table], dict):
            raise Error(f"cannot write {CONFIG_NAME}: [{table}] is not a table")
    chunks = [list(SAVE_HEADER)]
    scalars = [(key, value) for key, value in cfg.items() if not isinstance(value, dict)]
    if scalars:
        chunks.append([f"{_toml_key(key)} = {_toml_value(value)}"
                       for key, value in _ordered(scalars, _TOP_ORDER)])
    if "defaults" in cfg:
        chunks.append(["[defaults]"] + [f"{_toml_key(key)} = {_toml_value(value)}"
                                        for key, value in _ordered(list(cfg["defaults"].items()),
                                                                   _DEFAULTS_ORDER)])
    for table, order in (("models", _MODEL_ORDER), ("providers", _PROVIDER_ORDER)):
        for name, entry in (cfg.get(table) or {}).items():
            if not isinstance(entry, dict):
                raise Error(f"cannot write {CONFIG_NAME}: [{table}.{name}] is not a table")
            chunks.append(["[" + table + "." + _toml_key(name) + "]"] +
                          [f"{_toml_key(key)} = {_toml_value(value)}"
                           for key, value in _ordered(list(entry.items()), order)])
    for key, value in cfg.items():
        if key not in ("defaults", "models", "providers") and isinstance(value, dict):
            _dump_table([key], value, chunks)
    return "\n\n".join("\n".join(chunk) for chunk in chunks) + "\n"


def save(cfg, defaults=None):
    """Write the config back to ~/.agentkit/config.toml, atomically.

    The standard library parses TOML but does not write it, so this is the small writer for
    this schema: the known keys canonically ordered, every unknown key copied through with its
    value unchanged.  The text is built whole before anything is touched, then moved into
    place, so a value that will not write leaves the file it found behind.  The file keeps
    the 0600 install.sh gave it: a replace inherits the temp file's mode, not the old one's.
    `[defaults]` is written as `defaults`, a creation's (remember_defaults), and otherwise as
    the file has it, whatever `cfg` holds: a menu open for hours holds an older one, and a
    model removed since is only passed over in memory (load).
    """
    path = HOME / CONFIG_NAME
    if defaults is None:
        try:
            defaults = (_read_toml(path) or {}).get("defaults")
        except Error:
            defaults = None       # nothing readable to keep: `cfg`'s are written
    text = dump(cfg if defaults is None else {**cfg, "defaults": defaults})
    ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def model(cfg, name):
    """Resolve a config.toml key to its harness/model/effort/provider dict."""
    entry = cfg["models"].get(name)
    if entry is None:
        known = ", ".join(sorted(cfg["models"]))
        raise Error(f"unknown model {name!r}; ~/.agentkit/config.toml defines: {known}")
    for field in ("harness", "model", "effort", "provider"):
        if field not in entry:
            raise Error(f"~/.agentkit/config.toml: [models.{name}] is missing {field!r}")
    if entry["provider"] not in cfg["providers"]:
        raise Error(f"~/.agentkit/config.toml: [models.{name}].provider={entry['provider']!r} "
                    "has no [providers.*] entry")
    return entry


def model_label(entry):
    """The model id to show for one entry, for a model that names no id too.

    `default` -- and an empty id -- mean the harness picks: a Codex on a ChatGPT subscription
    takes no model of ours at all.  There is still a column to fill, so it says so rather than
    leaving a blank where an id belongs.
    """
    return entry["model"] if entry["model"] not in ("", DEFAULT_MODEL) else f"({DEFAULT_MODEL})"


def normalize_session(name):
    """Whitespace has the same spelling at creation, lookup and in rename pointers."""
    return " ".join(name.split()) if isinstance(name, str) else name


# Every file a seat owns under STATE is `<kind>-<seat>.<ext>`, named here and nowhere else: a
# rename moves them, a stop and the daily collector find them by this table.  Its locks and
# temporaries share the stem.
SEAT_FILES = {
    "session": "json",   # the seat's record, or a pointer a rename left at an old name
    "notify": "json",    # the last notification it sent, for the menu's state column
    "card": "json",      # its notification transition latch
    "seat": "json",      # its last classified live state and since when
    "hook": "json",      # what its harness's own lifecycle hooks say it is doing
    "compact": "json",   # tools/idle-compact.py compacted it
    "plan": "md",        # its plan, which the menu row reads its bar from
    "stop": "json",      # this turn's start, for the stop hook's rule
    "title": "json",     # the title last read from its conversation
    "input": "jsonl",    # each line ak typed, with its source and conversation
    "tell": "json",      # what other seats sent it with `ak tell`, until ak types it there
    "rulebook": "md",    # the rulebook its orchestrator was started on
    "verify": "lock",    # held by one verification of its plan at a time (`plan.verifying`)
    "rules": "md",       # the rulebook its prompt names once that one is out of date
}


def session_path(name):
    """The state file for one tmux session, whose name must stay a single path component."""
    name = normalize_session(name)
    if not isinstance(name, str) or not name or Path(name).name != name or name in (".", ".."):
        raise Error(f"invalid {SESSION_ENV} name {name!r}")
    return STATE / f"session-{name}.json"


def seat_file(kind, name):
    """The seat's file of one SEAT_FILES kind; raises Error for a name session_path refuses."""
    return session_path(name).with_name(f"{kind}-{normalize_session(name)}.{SEAT_FILES[kind]}")


def seat_files(kind):
    """(seat, path) for every file of one SEAT_FILES kind, in name order."""
    ext = SEAT_FILES[kind]
    return [(path.name[len(kind) + 1:-len(ext) - 1], path)
            for path in sorted(STATE.glob(f"{kind}-*.{ext}"))]


def seat_file_owner(path):
    """(kind, seat) for a `<kind>-<seat>.<anything>` file of a SEAT_FILES kind, None otherwise."""
    stem, dot, ext = Path(path).name.rpartition(".")
    kind, sep, name = stem.partition("-")
    return (kind, name) if dot and ext and sep and name and kind in SEAT_FILES else None


def notify_path(name):
    """Where the last notification a session sent is kept, for the menu's state column."""
    return seat_file("notify", name)


def card_path(name):
    """Where the per-session notification transition latch is kept."""
    return seat_file("card", name)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Error(f"cannot read {path}: {exc}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Error(f"{path}: {exc}")


def resolve_session(name):
    """The name a session goes by now.

    `ak orch rename` leaves `{"renamed": "<new>"}` behind in the old state file, because the
    orchestrator that was started under the old name still carries it in $AGENTKIT_SESSION and
    hands it to every `ak` it runs.  Following the chain here means those calls keep landing on
    the right selection, and the right menu row, after the rename.
    """
    name = normalize_session(name)
    # User-entered names are slugged by the seat launcher. Keep existing literal names,
    # including legacy tmux seats, but accept the same whitespace at lookup as at creation.
    if isinstance(name, str) and " " in name and not session_path(name).exists():
        from . import orch
        name = orch.session_name(name)
    seen = [name]
    for _ in range(RENAME_HOPS + 1):    # RENAME_HOPS renames, then the name after the last
        data = _read_json(session_path(name))
        if not isinstance(data, dict) or not isinstance(data.get("renamed"), str):
            return name
        name = normalize_session(data["renamed"])
        if name in seen:
            raise Error(f"{session_path(seen[0])}: the rename chain loops through {' -> '.join(seen)}")
        seen.append(name)
    raise Error(f"{session_path(seen[0])}: more than {RENAME_HOPS} renames deep")


def current_session():
    """The session this process runs in, by its current name, or None outside a seat."""
    name = os.environ.get(SESSION_ENV)
    return resolve_session(name) if name else None


INBOX_ENV = "AGENTKIT_INBOX_SESSION"


def inbox():
    """The seat other people's PRs are offered in and merged from (`ak watch`); a test points it
    elsewhere.  One home: the gh shim lets this seat's `gh pr merge` through, and watch asks it."""
    return os.environ.get(INBOX_ENV) or "inbox"


def check_stop_owner(owner):
    """A seat stops only its own work; the owner outside a seat may stop anything."""
    caller = current_session()
    if caller and isinstance(owner, str) and owner:
        owner = resolve_session(owner)
        if owner != caller:
            raise Error(f"owned by seat {owner}; tell it instead: ak tell {owner} \"...\"")


def _validate_session(cfg, name, data):
    if not isinstance(data, dict):
        raise Error(f"{session_path(name)}: expected a JSON object")
    orchestrator, workers = data.get("orchestrator"), data.get("workers")
    if not isinstance(orchestrator, str):
        raise Error(f"{session_path(name)}: orchestrator must be a model name")
    try:
        model(cfg, orchestrator)
    except Error as exc:
        raise Error(f"{session_path(name)}: {exc}") from None
    for role in ("workers", "reviewers"):
        if role == "reviewers" and role not in data:
            continue
        listed = data.get(role)
        # no executor is a choice once reviewers are named: the orchestrator builds everything
        empty_ok = role == "workers" and "reviewers" in data
        if (not isinstance(listed, list) or not (listed or empty_ok)
                or any(not isinstance(worker, str) for worker in listed)):
            raise Error(f"{session_path(name)}: {role} must be a non-empty list of model names")
        for worker in listed:
            try:
                model(cfg, worker)
            except Error as exc:
                raise Error(f"{session_path(name)}: {exc}") from None
        if len(set(listed)) != len(listed):
            raise Error(f"{session_path(name)}: {role} contains duplicates")
    # the orchestrator's own model may work for it too: nothing here excludes one from the other
    # Whatever else the record carries -- where the seat ran, when, and the conversation the
    # harness kept -- is handed back untouched: only the model fields are this file's to judge.
    return {**data, "orchestrator": orchestrator, "workers": workers}


@contextmanager
def _record_lock(path):
    """One writer at a time for a seat's record: each reads, merges and replaces the whole
    file, and they share the one temporary file beside it.  Always taken last, inside any
    other lock, and held only for that write, so it orders with nothing."""
    with path.with_name(f".{path.stem}.lock").open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write_json(path, data, prepare=True):
    if prepare:
        ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def save_session(cfg, name, orchestrator, workers, extra=None):
    """Atomically record the models selected for a newly created session, and where it runs.

    `extra` is what the seat is besides its models -- its directory, the moment it was created,
    the harness conversation it holds -- because a record has to say enough to open the seat
    again once tmux is no longer holding it. New seats inherit explicit default reviewers;
    loading an older record never adds them.
    """
    reviewers = cfg.get("defaults", {}).get("reviewers")
    selection = _validate_session(cfg, name, {"orchestrator": orchestrator, "workers": workers,
                                              **({"reviewers": list(reviewers)}
                                                 if reviewers is not None else {}),
                                              **(extra or {})})
    ensure_dirs()
    with _record_lock(session_path(name)):
        _write_json(session_path(name), selection, prepare=False)
    return selection


def discard_session(name, created):
    """Remove `name`'s record only while it is still the one saved at `created`: a launch that
    failed takes back its own record, never one another launch saved under the name since."""
    path = session_path(name)
    if not path.parent.is_dir():
        return
    with _record_lock(path):
        try:
            data = _read_json(path)
        except Error:
            return      # unreadable is not known to be its own
        if isinstance(data, dict) and data.get("created") == created:
            path.unlink(missing_ok=True)


def remember_defaults(record):
    """[defaults] as the seat just created was given: what the next `n` starts from, and the
    one write of them (save).  The file is read again first, so nothing changed in it since
    is written back over; a failed write keeps the ones before."""
    try:
        cfg = load()
        # a file from before it held the models (max_runs alone) loads as the shipped one: its
        # own keys are written back over the shipped ones, as they were
        cfg.update((key, value) for key, value in (_read_toml(HOME / CONFIG_NAME) or {}).items()
                   if key not in ("defaults", "tiers", "models", "providers"))
        save(cfg, {key: record[key] for key in _DEFAULTS_ORDER if key in record})
    except (Error, OSError):
        pass    # the seat is made all the same


def update_session(name, **fields):
    """Merge fields into an existing session record; a session with no record is left alone.

    A seat somebody made by hand (`tmux new`) has no record and gets none here: it is listed
    from tmux, not from this directory, and inventing a file for it would only claim to know
    things -- which models, which conversation -- that nobody ever chose.  A field given as
    None is removed rather than written, except for repo: null records a deliberate lack of
    project, so old-record inference does not run again.
    """
    path = session_path(name)
    if not path.parent.is_dir():
        return None
    # read and written under the record's lock: a concurrent writer of other fields
    # never writes back the record as it was before this one
    with _record_lock(path):
        data = _read_json(path)
        if not isinstance(data, dict) or "renamed" in data:
            return None
        if all(data.get(key) == value and (key != "repo" or key in data)
               for key, value in fields.items()):
            return data
        for key, value in fields.items():
            if value is None and key != "repo":
                data.pop(key, None)
            else:
                data[key] = value
        # The record's directory already exists. In particular, project inference while
        # listing seats must not prepare or change metadata on run/worktree directories.
        _write_json(path, data, prepare=False)
    return data


def _session_files():
    """(name, contents) for every session file, records and rename pointers alike."""
    if not STATE.exists():
        return
    for name, path in seat_files("session"):
        try:
            data = _read_json(path)
        except Error:
            continue
        if isinstance(data, dict):
            yield name, data


def session_records():
    """{name: record} for every session file that is a record rather than a rename pointer."""
    return {name: data for name, data in _session_files() if "renamed" not in data}


def session_aliases():
    """{old name: where it leads} for the pointers `ak orch rename` left behind.

    An alias is not a free name while it leads anywhere: the orchestrator renamed under it still
    carries the old name in $AGENTKIT_SESSION and hands it to every `ak` it runs, so a new seat
    taking that name would take those calls with it.  A chain that loops or runs too deep leads
    to itself here, which is the caller's cue that it is no name to hand out either.
    """
    found = {}
    for name, data in _session_files():
        if "renamed" not in data:
            continue
        try:
            found[name] = resolve_session(name)
        except Error:
            found[name] = name
    return found


def load_session(cfg, name, required=True):
    """Read and validate a session selection, following renames; optionally tolerate no file."""
    name = resolve_session(name)
    path = session_path(name)
    data = _read_json(path)
    if data is None:
        if not required:
            return None
        raise Error(f"{SESSION_ENV}={name!r}, but {path} does not exist")
    return _validate_session(cfg, name, data)


def rename_session(old, new):
    """Move the selection to its new name and leave a pointer at the old one."""
    target = resolve_session(new)
    if target not in (old, new):
        raise Error(f"{new!r} points at another session; pick a name that is not a rename")
    ensure_dirs()
    if target == new:
        # a free name: the plan a gone seat left there, or under a name still leading there,
        # is not this seat's
        from . import plan
        plan.forget(new)
    # under both records' locks: a field written to the old one meanwhile moves with it
    with _record_lock(session_path(old)), _record_lock(session_path(new)):
        selection = _read_json(session_path(old))
        if isinstance(selection, dict) and "renamed" not in selection:
            _write_json(session_path(new), selection, prepare=False)
        elif target == old:
            # A legacy seat has no selection to overwrite its former pointer with.
            session_path(new).unlink(missing_ok=True)
        _write_json(session_path(old), {"renamed": new}, prepare=False)
    # Every older name of this seat leads to `old`, straight or through its other old names: it
    # points at `new` now, so no chain passes one rename however often a seat is renamed (its
    # title follows the conversation), and a chain left deeper than a walk follows recovers.
    pointers = {name: normalize_session(data["renamed"]) for name, data in _session_files()
                if isinstance(data.get("renamed"), str)}
    for name, leads in pointers.items():
        seen, step = {name}, leads
        while step != old and step in pointers and step not in seen:
            seen.add(step)
            step = pointers[step]
        if step != old:
            continue
        with _record_lock(session_path(name)):
            try:
                pointer = _read_json(session_path(name))
            except Error:
                continue
            if isinstance(pointer, dict) and normalize_session(pointer.get("renamed")) == leads:
                _write_json(session_path(name), {"renamed": new}, prepare=False)
    # The running orchestrator keeps reading the rulebook it was started on, and its hooks keep
    # the turn's latch under the name it was started with.  Back to a name it had, what the
    # seat wrote under it since is kept rather than moved over: a seat renamed still writes its
    # plan under the name it was launched with, and `plan.path` reads the plan under every name
    # the seat had, the newest one winning.
    for kind in SEAT_FILES.keys() - {"session", "rulebook", "stop"}:
        was, now = seat_file(kind, old), seat_file(kind, new)
        if was.exists() and not (target == old and now.exists()):
            was.replace(now)


def active_session(cfg):
    """The active session selection, or None outside an orchestrator's environment."""
    name = current_session()
    if not name:
        return None
    selection = load_session(cfg, name, required=False)
    return {"name": name, **selection} if selection else None


def server_alias():
    """The ssh alias of the server, which install.sh records on a client and nowhere else."""
    try:
        return (STATE / "server").read_text().strip() or None
    except OSError:
        return None


def workers(cfg):
    """The session's selection, else the default workers."""
    session = active_session(cfg)
    return session["workers"] if session else list(cfg["defaults"]["workers"])


def reviewers(cfg):
    """An omitted reviewer selection uses that same record's workers, never another seat's."""
    selection = active_session(cfg) or cfg["defaults"]
    return list(selection.get("reviewers", selection["workers"]))


def role_groups(cfg, workers=None, reviewers=None):
    """Bind unbound picks only for explicit reviewers; preserve absence for legacy overrides."""
    if workers is None:
        selection = active_session(cfg) or cfg["defaults"]
        if "reviewers" in selection:
            workers = selection["workers"]
            if reviewers is None:
                reviewers = selection["reviewers"]
    return workers, reviewers


def adapter(harness):
    root = Path(os.environ.get(ADAPTER_DIR_ENV) or REPO / "adapters").expanduser()
    path = root / f"{harness}.sh"
    if not path.exists():
        raise Error(f"no adapter for harness {harness!r}: {path} does not exist")
    if not os.access(path, os.X_OK):
        raise Error(f"adapter {path} is not executable; chmod +x it")
    return path


_MANIFESTS = {}


def manifest(harness):
    """adapters/<harness>.toml: everything agentkit knows about that harness's screen.

    Beside the adapter script, and read the same way -- $AGENTKIT_ADAPTER_DIR first -- except
    that a directory of fake adapters replaces the model calls, not the screen knowledge, so a
    missing file there falls back to this checkout's own.  A harness with no manifest reads as
    an empty one: nothing is recognised on its screen, and nothing is typed into it.
    Cached by path and mtime, because it is read on every menu draw and every watch tick.
    """
    if not isinstance(harness, str) or not HARNESS.fullmatch(harness):
        return {}
    override = os.environ.get(ADAPTER_DIR_ENV)
    roots = [Path(override).expanduser(), REPO / "adapters"] if override else [REPO / "adapters"]
    for root in roots:
        path = root / f"{harness}.toml"
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            continue
        cached = _MANIFESTS.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise Error(f"{path}: {exc}")
        _MANIFESTS[path] = (stamp, data)
        return data
    return {}


def seat_env_names():
    """The variables a launch sets for its seat alone, as the adapter manifests declare them.

    `[launch] seat_env` in adapters/<h>.toml names what a harness is told when its seat opens
    and what nothing that seat starts may be told -- where this seat's rulebook is, say.  A
    worker, a done-when command, or a second harness started from that seat would otherwise be
    working to the orchestrator's rules instead of its own role's.  The names come from the
    manifests because nothing here knows one harness from another, let alone what it calls its
    own variables; the manifests themselves are cached by mtime.
    """
    names = set()
    for _, data in manifests():
        block = data.get("launch")
        if isinstance(block, dict):
            names.update(n for n in block.get("seat_env") or [] if isinstance(n, str))
    return names


def manifests():
    """Every adapter manifest, as (harness, manifest), from the same places `manifest` reads."""
    override = os.environ.get(ADAPTER_DIR_ENV)
    roots = [Path(override).expanduser(), REPO / "adapters"] if override else [REPO / "adapters"]
    for root in roots:
        try:
            paths = sorted(root.glob("*.toml"))
        except OSError:
            continue
        for path in paths:
            yield path.stem, manifest(path.stem)


def instruction_ceiling():
    """The most of a project's AGENTS.md every harness reads on its own, and whose limit it is.

    `[instructions] read_limit` in adapters/<h>.toml is how many bytes that harness reads of
    the file before it drops the rest unannounced.  The smallest wins: a project's file has to
    reach every harness whole, ak's prompts and a harness opened in the checkout alike.  None
    when no manifest declares one, and then nothing limits the file's size.
    """
    limits = []
    for harness, data in manifests():
        block = data.get("instructions")
        limit = block.get("read_limit") if isinstance(block, dict) else None
        if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
            limits.append((limit, harness))
    return min(limits) if limits else None


def seat_state_path(name):
    """Where the seat's last classified live state and its `since` are kept."""
    return seat_file("seat", name)


def hook_facts_path(name):
    """Where a harness's own lifecycle hooks write what that seat is doing."""
    return seat_file("hook", name)


def compact_path(name):
    """Where tools/idle-compact.py writes down that it compacted that seat."""
    return seat_file("compact", name)


def plan_path(name):
    """The session's plan, a markdown list the menu row reads its bar from."""
    return seat_file("plan", name)


def runs_moved_path():
    """Touched whenever a seat's run moves -- a step, a round, an ending -- so an open menu, which
    watches it, reads its rows again."""
    return STATE / "runs-moved"


def stop_path(name):
    """Where hooks/seat-state.sh leaves this turn's start for the stop hook's rule."""
    return seat_file("stop", name)


def title_path(name):
    """Where the seat's conversation title and how far it was read are kept between ticks."""
    return seat_file("title", name)


def rulebook_path(name):
    """The rulebook file for a seat of any name: whatever cannot be a file name becomes `-`."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", " ".join(str(name).split())).strip("-.") or "seat"
    return seat_file("rulebook", name)


def rulebook_text():
    """The rulebook a session receives: the vision, the repo's rules, then this host's own.

    Only a host that has written no rules of its own has none: a rules.md that is there and
    cannot be read is an error, never an empty one, because a session opened without rules the
    owner did write is a session working to rules nobody chose.
    """
    body = (REPO / "orchestrator.md").read_text()
    try:
        agents = (REPO / "AGENTS.md").read_text()
    except FileNotFoundError:
        agents = ""
    vision = re.search(r"(?ms)^## What ak is for(?:\n|\Z).*?(?=^## |\Z)", agents)
    if vision:
        body = f"{vision.group().rstrip()}\n\n{body}"
    try:
        local = (HOME / "rules.md").read_text()
    except FileNotFoundError:
        return body
    return f"{body.rstrip()}\n\n{local}" if local.strip() else body


def seat_rulebook(session, repo=None):
    """What `session`'s rulebook file holds when it opens now: `rulebook_text`, the AGENTS.md of
    the project it is filed under -- `repo`, else its record's -- as on that project's default
    branch: what its workers get, as its launch or the tick last fetched it
    (`orch.fetch_project`); and an unnamed seat's instruction to name itself."""
    from . import run
    body = rulebook_text()
    record = session_records().get(session, {})
    repo = record.get("repo") if repo is None else repo
    # the full name: a branch or tag called origin/HEAD would win the short one
    project = run.agents_body(repo, "refs/remotes/origin/HEAD")
    if project:
        body = (f"{body.rstrip()}\n\n# The project's AGENTS.md\n\nThe rules of {Path(repo).name}, "
                "the project this session is filed under, as on its default branch: its workers "
                f"get the same.\n\n{project}\n")
    if record.get("unnamed"):
        body = (f"{body.rstrip()}\n\nThis seat is unnamed. As soon as the conversation tells you "
                "what the job is, name this seat with `ak orch rename --auto <name>`. Choose the "
                "shortest possible name, at most three words, saying what the work is.\n")
    return body


def rulebook_digest(data):
    """sha256 of a rulebook's text or bytes: what a seat's record keeps of the one it read."""
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def accounts(cfg, provider):
    """The subscriptions one provider lists as `accounts`, in the order they are tried.

    [] for a provider that lists none, which is one login, exactly as a provider always was.
    """
    entry = cfg["providers"].get(provider)
    listed = entry.get("accounts") if isinstance(entry, dict) else None
    return list(listed) if isinstance(listed, list) else []


def account_label(cfg, provider, account, name):
    """What a person reads for one of a provider's subscriptions: `name`, the provider's own,
    and for one of several its place in `accounts` in roman numerals -- `Claude II`.  The
    account's name in `accounts` is ak's own and is never shown; one no longer listed there
    keeps it, since no place would say which one it is."""
    listed = accounts(cfg, provider)
    if account not in listed:
        return name if account in (None, DEFAULT_ACCOUNT) else f"{name} {account}"
    if len(listed) < 2:
        return name
    number, numeral = listed.index(account) + 1, ""
    for value, digits in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
                          (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"),
                          (4, "IV"), (1, "I")):
        count, number = divmod(number, value)
        numeral += digits * count
    return f"{name} {numeral}"


def account_env(account):
    """What an adapter call for that account is told: its name in AGENTKIT_ACCOUNT, and for
    `default` the empty name -- the login the adapter uses when no account is named at all."""
    return {ACCOUNT_ENV: "" if account in (None, DEFAULT_ACCOUNT) else account}


def kept_logins():
    """Each login `− remove` took out of ak and left on disk, oldest first, as (provider,
    account, label): a subscription it took out of `accounts`, or the usual login of a provider
    it removed whole, with the name its usage row had.  `+ add` offers them back.  [] where
    there is no record, or none that can be read."""
    try:
        kept = _read_json(STATE / KEPT_LOGINS)
    except Error:
        return []
    return [tuple(entry) for entry in kept if isinstance(entry, list) and len(entry) == 3] \
        if isinstance(kept, list) else []


def keep_login(provider, account, label):
    """Record one login `− remove` takes out, in place of an older record of the same one."""
    kept = [entry for entry in kept_logins() if entry[:2] != (provider, account)]
    _write_json(STATE / KEPT_LOGINS, [*kept, (provider, account, label)])


def provider_harness(cfg, provider):
    """The harness of the first model of a provider -- that adapter owns its usage call."""
    for name, entry in cfg["models"].items():
        if entry.get("provider") == provider:
            return entry["harness"], name
    raise Error(f"~/.agentkit/config.toml: [providers.{provider}] has no model")


def ensure_dirs():
    for d in (HOME, RUNS, WT, STATE, SECRETS, TMP, ENV, WORK, HOME / "jobs"):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(d, 0o700)   # a dir someone else created stays 0700 too
