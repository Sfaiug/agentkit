"""config.toml loading, model resolution, and every agentkit path."""

import datetime
import json
import math
import os
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home() / ".agentkit"
RUNS, WT, STATE, SECRETS, TMP, ENV, WORK = (
    HOME / n for n in ("runs", "wt", "state", "secrets", "tmp", "env", "work"))


def __getattr__(name):
    # JOBS follows HOME wherever a test or a checkout moves it, so sandboxing HOME is
    # enough to keep job receipts out of the owner's real ~/.agentkit; anything patching
    # config.JOBS explicitly keeps working, since that shadows this fallback.
    if name == "JOBS":
        return HOME / "jobs"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


AFTER_KEY = "after"  # task front matter `after:` names another task file in the same job
JOB_DIR_ENV = "AGENTKIT_JOB_DIR"  # the `ak run --bg` job child this receipt belongs to
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
HARNESS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")   # a harness name is one path component


RUN_DIR_ENV = "AGENTKIT_RUN_DIR"
ADAPTER_DIR_ENV = "AGENTKIT_ADAPTER_DIR"   # adapters/ elsewhere: the offline smoke checks
SESSION_ENV = "AGENTKIT_SESSION"
ACCOUNT_ENV = "AGENTKIT_ACCOUNT"           # which of a provider's `accounts` an adapter call is for
DEFAULT_ACCOUNT = "default"                # ... the login it has when it lists none: the empty name
UNATTENDED_ENV = "AGENTKIT_UNATTENDED"   # set below a run loop: what it starts is machinery
CODE = Path.home() / "code"                # where the checkouts live, and where a new seat opens
RENAME_HOPS = 8                            # how many renames a session name is followed through
DEFAULT_MODEL = "default"                  # config.toml: the harness runs its own model, no -m
SESSION_STALE = 7 * 86400                  # a record whose session has been gone this long goes
RUN_DEFAULTS = {"max_runs": 0, "max_gates": 3}
CONFIG_NAME = "config.toml"                # the one config file, under HOME: never in the checkout
DEFAULT_CONFIG_NAME = "config.default.toml"   # ... whose shipped default install.sh copies there
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")   # the effort words for a
                               # harness whose adapter manifest names none of its own
CATALOG_TTL = 60               # seconds a harness's model list is reused before it is asked again


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
    """How many done-when gates of one repository run at once, host-wide; zero means no cap."""
    return _count_setting("max_gates")


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
        try:
            text = Path("/proc/meminfo").read_text()
            mem_total_mb = next(float(line.split()[1]) / 1024
                                for line in text.splitlines()
                                if line.startswith("MemTotal:"))
        except (OSError, StopIteration, ValueError, IndexError):
            mem_total_mb = 0
    default = max(3072, mem_total_mb * 0.20)
    return _resource_setting("min_free_mb", "AK_MIN_FREE_MB", default)


def max_load(cpus=None):
    """Maximum one-minute load, defaulting to the host's processor count."""
    cpus = os.cpu_count() if cpus is None else cpus
    default = max(1, cpus or 1)
    return _resource_setting("max_load", "AK_MAX_LOAD", default)


def run_memory_max_mb():
    """The per-run memory cap in MiB, or None when the config leaves it unset.

    Unset is not zero.  The caller then takes the smaller of 4 GB and 40% of
    the slice ceiling.  A present value is that cap, whatever the ceiling is:
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
    and the workers a new seat starts with.  A file from before it said that with two tier
    lists, and reads as what they meant outside a session: the first of A orchestrating for B
    without it.  Nothing writes it back until the owner saves from the `c` screen, which then
    writes `[defaults]` and the top-level `pace_margin` in their place.
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
    # A default nobody named is the first model, the same answer remove_provider() gives a
    # default it empties, so a seat can still start with Enter.
    if defaults.setdefault("orchestrator", names[0]) not in names:
        raise Error(f"{path}: [defaults].orchestrator must be one of {', '.join(names)} "
                    f"(got {defaults['orchestrator']!r})")
    workers = defaults.setdefault("workers", [])
    if (not isinstance(workers, list) or any(name not in names for name in workers)
            or len(set(workers)) != len(workers)):
        raise Error(f"{path}: [defaults].workers must list distinct models of "
                    f"{', '.join(names)} (got {workers!r})")
    if not workers:
        defaults["workers"] = [names[0]]
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
    """Every model the config offers, in file order: each one can orchestrate, and each can work.

    A `[models.*]` entry is offered once its provider has a `[providers.*]` table; one whose
    provider has none stays in the file and out of every choice.
    """
    return [name for name, entry in cfg["models"].items()
            if isinstance(entry, dict) and isinstance(entry.get("provider"), str)
            and entry["provider"] in cfg["providers"]]


def remove_provider(cfg, name):
    """Take one provider out of `cfg`: its table, its models, and their places in [defaults].

    A default this leaves empty falls back to the first model still offered, so a new seat
    still starts with Enter.  The last provider cannot go, since a config with no model has
    nothing to start a seat on.  Its usage row goes with its table: the menu and `ak usage`
    list, and probe, only the providers the config has.  The caller saves.
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
    _fall_back(cfg["defaults"], left)
    return cfg


def remove_model(cfg, name):
    """Take one model out of `cfg`, and out of [defaults], the way remove_provider takes one
    provider's: a default this leaves empty falls back to the first model still offered, and
    the last model cannot go.  Its provider stays, settings and all, so another of its models
    can be added; a `usage_model` naming it goes, and that usage call falls to the provider's
    first model.  The caller saves.
    """
    left = [model for model in offered(cfg) if model != name]
    if not left:
        raise Error(f"{name} is the last model; add another before removing it")
    provider = cfg["providers"][cfg["models"].pop(name)["provider"]]
    if provider.get("usage_model") == name:
        del provider["usage_model"]
    _fall_back(cfg["defaults"], left)
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


def _fall_back(defaults, left):
    """[defaults] kept to the models `left`: one it empties takes the first of them."""
    if defaults.get("orchestrator") not in left:
        defaults["orchestrator"] = left[0]
    defaults["workers"] = [model for model in defaults.get("workers") or []
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
                              encoding="utf-8", errors="replace", env=child_env())
        out = proc.stdout if proc.returncode == 0 else ""
    except (Error, OSError, subprocess.TimeoutExpired):
        out = ""
    models = [{"id": fields[0], "label": fields[1] or fields[0], "efforts": fields[2].split()}
              for fields in (line.split("\t") for line in out.splitlines())
              if len(fields) == 3 and fields[0]] or catalog_table(harness)
    _CATALOGS[harness] = (now, models)
    return models


def efforts(harness, model=None):
    """That harness's effort words, in the order the `c` screen cycles them -- or that model's.

    Given a model its catalog says the efforts of, those are the answer -- `none` alone for one
    that runs at no effort.  Otherwise `[effort] levels` in its adapter manifest is the
    vocabulary; a harness that names none -- a fourth one, or the echo fixture -- takes the
    fixed list, which holds every word the shipped defaults use.
    """
    if model is not None:
        for entry in catalog(harness):
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
_DEFAULTS_ORDER = ("orchestrator", "workers")
_MODEL_ORDER = ("harness", "model", "effort", "provider", "reviews_own_provider", "meter")
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


def save(cfg):
    """Write the config back to ~/.agentkit/config.toml, atomically.

    The standard library parses TOML but does not write it, so this is the small writer for
    this schema: the known keys canonically ordered, every unknown key copied through with its
    value unchanged.  The text is built whole before anything is touched, then moved into
    place, so a value that will not write leaves the file it found behind.  The file keeps
    the 0600 install.sh gave it: a replace inherits the temp file's mode, not the old one's.
    """
    text = dump(cfg)
    ensure_dirs()
    path = HOME / CONFIG_NAME
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


def session_path(name):
    """The state file for one tmux session, whose name must stay a single path component."""
    name = normalize_session(name)
    if not isinstance(name, str) or not name or Path(name).name != name or name in (".", ".."):
        raise Error(f"invalid {SESSION_ENV} name {name!r}")
    return STATE / f"session-{name}.json"


def notify_path(name):
    """Where the last notification a session sent is kept, for the menu's state column."""
    name = normalize_session(name)
    return session_path(name).with_name(f"notify-{name}.json")


def card_path(name):
    """Where the per-session notification transition latch is kept."""
    name = normalize_session(name)
    return session_path(name).with_name(f"card-{name}.json")


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
    for _ in range(RENAME_HOPS):
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
    if (not isinstance(workers, list) or not workers
            or any(not isinstance(worker, str) for worker in workers)):
        raise Error(f"{session_path(name)}: workers must be a non-empty list of model names")
    for worker in workers:
        try:
            model(cfg, worker)
        except Error as exc:
            raise Error(f"{session_path(name)}: {exc}") from None
    if len(set(workers)) != len(workers):
        raise Error(f"{session_path(name)}: workers contains duplicates")
    # the orchestrator's own model may work for it too: nothing here excludes one from the other
    # Whatever else the record carries -- where the seat ran, when, and the conversation the
    # harness kept -- is handed back untouched: only the two model fields are this file's to judge.
    return {**data, "orchestrator": orchestrator, "workers": workers}


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
    again once tmux is no longer holding it.
    """
    selection = _validate_session(cfg, name, {"orchestrator": orchestrator, "workers": workers,
                                              **(extra or {})})
    _write_json(session_path(name), selection)
    return selection


def update_session(name, **fields):
    """Merge fields into an existing session record; a session with no record is left alone.

    A seat somebody made by hand (`tmux new`) has no record and gets none here: it is listed
    from tmux, not from this directory, and inventing a file for it would only claim to know
    things -- which models, which conversation -- that nobody ever chose.  A field given as
    None is removed rather than written, except for repo: null records a deliberate lack of
    project, so old-record inference does not run again.
    """
    path = session_path(name)
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
    for path in sorted(STATE.glob("session-*.json")):
        try:
            data = _read_json(path)
        except Error:
            continue
        if isinstance(data, dict):
            yield path.name[len("session-"):-len(".json")], data


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
    if _read_json(session_path(new)) is not None and resolve_session(new) != new:
        raise Error(f"{new!r} points at another session; pick a name that is not a rename")
    selection = _read_json(session_path(old))
    ensure_dirs()
    if isinstance(selection, dict) and "renamed" not in selection:
        tmp = session_path(new).with_suffix(".tmp")
        tmp.write_text(json.dumps(selection, indent=2) + "\n")
        tmp.replace(session_path(new))
    tmp = session_path(old).with_suffix(".tmp")
    tmp.write_text(json.dumps({"renamed": new}) + "\n")
    tmp.replace(session_path(old))
    for was, now in ((notify_path(old), notify_path(new)),
                     (card_path(old), card_path(new)),
                     (seat_state_path(old), seat_state_path(new)),
                     (hook_facts_path(old), hook_facts_path(new)),
                     (compact_path(old), compact_path(new)),
                     (plan_path(old), plan_path(new)),
                     (stop_path(old), stop_path(new))):
        if was.exists():
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
    override = os.environ.get(ADAPTER_DIR_ENV)
    roots = [Path(override).expanduser(), REPO / "adapters"] if override else [REPO / "adapters"]
    names = set()
    for root in roots:
        try:
            paths = sorted(root.glob("*.toml"))
        except OSError:
            continue
        for path in paths:
            block = manifest(path.stem).get("launch")
            if isinstance(block, dict):
                names.update(n for n in block.get("seat_env") or [] if isinstance(n, str))
    return names


def seat_state_path(name):
    """Where the seat's last classified live state and its `since` are kept."""
    return session_path(name).with_name(f"seat-{normalize_session(name)}.json")


def hook_facts_path(name):
    """Where a harness's own lifecycle hooks write what that seat is doing."""
    return session_path(name).with_name(f"hook-{normalize_session(name)}.json")


def compact_path(name):
    """Where tools/idle-compact.py writes down that it compacted that seat."""
    return session_path(name).with_name(f"compact-{normalize_session(name)}.json")


def plan_path(name):
    """The session's plan, a markdown list the menu row reads its bar from."""
    return session_path(name).with_name(f"plan-{normalize_session(name)}.md")


def stop_path(name):
    """Where hooks/seat-state.sh leaves this turn's start for the stop hook's rule."""
    return session_path(name).with_name(f"stop-{normalize_session(name)}.json")


def accounts(cfg, provider):
    """The subscriptions one provider lists as `accounts`, in the order they are tried.

    [] for a provider that lists none, which is one login, exactly as a provider always was.
    """
    entry = cfg["providers"].get(provider)
    listed = entry.get("accounts") if isinstance(entry, dict) else None
    return list(listed) if isinstance(listed, list) else []


def account_env(account):
    """What an adapter call for that account is told: its name in AGENTKIT_ACCOUNT, and for
    `default` the empty name -- the login the adapter uses when no account is named at all."""
    return {ACCOUNT_ENV: "" if account in (None, DEFAULT_ACCOUNT) else account}


def provider_harness(cfg, provider):
    """The harness of the first model of a provider -- that adapter owns its usage call."""
    for name, entry in cfg["models"].items():
        if entry.get("provider") == provider:
            return entry["harness"], name
    raise Error(f"~/.agentkit/config.toml: [providers.{provider}] has no model")


def task_afters(task_path):
    """`after:` values from a task file's front matter, one per line, repeatable.

    Each line names the basename or title of another task file in the same job;
    a comma-separated line names several. Blank values are ignored.
    """
    try:
        text = Path(task_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise Error(f"cannot read {task_path}: {exc}")
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not match:
        return []
    found = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        if key.strip() != AFTER_KEY:
            continue
        value = value.split("#", 1)[0].strip()
        for part in value.split(","):
            part = part.strip()
            if part:
                found.append(part)
    return found


def ensure_dirs():
    for d in (HOME, RUNS, WT, STATE, SECRETS, TMP, ENV, WORK, HOME / "jobs"):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(d, 0o700)   # a dir someone else created stays 0700 too
