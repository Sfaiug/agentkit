"""A harness is a plugin: `adapters/<name>.sh`, `adapters/<name>.toml`, and nothing else.

`load(name)` answers with every hook a harness can implement, defaulted, so a harness that
brings no Python at all works: the adapter script runs it, the adapter manifest says what its
screen, its quota, its update and its conversation are, and the defaults here answer the rest.
A harness that needs Python puts it in `agentkit/harness/<name>.py` and implements only the
hooks it has something to say about -- `claude.py` the transcript it writes and the counts by
model its results report, `codex.py` the launch receipt its thread is proven by,
`grokbuild.py` the session directory it opens, `muse.py` its launcher build, the snapshot an
upgrade is put back from, its own usage probe, the receipt its SessionStart hook writes its
session into and its registry moves on `/new`,
the session store its tokens and messages are in and the sessions gc ends,
`opencode.py` the receipt it keeps its seat's session in, the endpoint that says
how a model is paid and the sessions gc ends,
`antigravity.py` the database each of its conversations is, and which one a seat's agy holds
open.  A script its adapter runs on its own sits beside its module, named for it:
`muse_usage.py` is Muse's billed usage probe.

No module outside this package names a harness: the core asks
`harness.load(config.model(cfg, m)["harness"]).<hook>(...)` and takes the answer.
"""

import contextlib
import contextvars
import fcntl
import functools
import importlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
import re
import sqlite3
import time

from .. import config

LAUNCHER = "launcher"      # `id_source`: the id in the record is one the launcher handed out
# What a launch writes about the conversation it owns: the launcher's own id, each
# harness's receipt, and the title that launch takes. A restart that fails puts these
# back from the record as it was, so the seat keeps its own conversation; a typing receipt
# keeps them where its conversation is not named yet (`Harness.receipt`).
LAUNCH_KEYS = ("conversation", "resumable", "id_source", "before", "codex_launch",
               "codex_history", "opencode_launch", "muse_launch", "antigravity_launch",
               "antigravity_open", "session_title", "title_sync")
FRESH_WORDS = "no conversation recorded; it starts fresh"   # `[conversation] fresh_words`

# `[update]`: how `ak update` moves this harness, and what it cannot do.  A harness that names
# no `version` and `upgrade` is not one `ak update` touches.  `latest` names its newest release,
# which the tick keeps it on in the background.
UPDATE = {"version": None, "upgrade": None, "revert": None, "latest": None, "env": {},
          "cannot": ""}
# `[usage]`: what its usage call needs beyond `<adapter> usage`.  `none` is the harness
# without a meter at all: no reading is a neutral provider, never a failed probe.
# `probe_every` is how often the harness may be asked at all, in seconds: its own fact,
# and None where the manifest names none, which is the host's usual minute.
USAGE = {"capture": False, "strips_timestamp": False, "reset": False, "none": False,
         "probe_every": None}
# `[stall]`: the words no one harness owns, read for every harness beside its manifest's own:
# HTTP's, the shell's, a command line's, a login's and a model name's, which any harness may
# pass on.  An outage's status code counts only beside HTTP, a status or an API error.
STALL = {"quotas": ("402", "billing_error", "payment required"),
         "refusals": ("API Error", "529", "unexpected status"),
         "outages": ("overloaded", "at capacity", "Internal server error", "Bad Gateway",
                     "Gateway Timeout", "Service unavailable", "The service is busy",
                     "idle timeout", "Can't reach the API server", "HTTP~5##", "status~5##",
                     "API Error~5##"),
         "faults": ("command not found", "Argument list too long", "not installed",
                    "unknown flag", "unknown flags", "unknown shorthand flag",
                    "unknown shorthand flags", "unknown option", "unknown options",
                    "unknown argument", "unknown arguments", "unknown command",
                    "unknown commands", "unknown model", "unknown models",
                    "unrecognized option", "unrecognized options", "unrecognized argument",
                    "unrecognized arguments", "unexpected argument", "unexpected arguments",
                    "invalid option", "invalid options", "invalid model", "invalid models",
                    "model … not found", "model … not exist", "model … not supported",
                    "model~not~found", "ModelNotFoundError", "not logged in", "please~log~in",
                    "please~run~log~in", "unauthorized", "unauthorised",
                    "authentication~failed", "authentication~required", "authentication~error",
                    "invalid~api~key", "invalid~x~api~key")}
# A rate limit, in any harness's words: HTTP's 429 and the provider asking to slow down, which
# alone never says the window is spent.  A quota word that says one of these is only a limit.
LIMITS = ("429", "too many requests", "rate~limit", "rate~limited", "rate~limit~error")
# What a failed turn's own output says, as `Harness.failure` reads it: the account's window is
# spent, or only rate limited, the provider declined the turn or is down, or the harness never
# ran the turn at all.
SPENT, LIMITED, REFUSAL, OUTAGE, FAULT = "spent", "limited", "refusal", "outage", "fault"

_LOADED = {}


def says(text, word):
    """Does `text` say `word` on its own: never inside a longer word, nor its digits inside a
    longer number, a file path or a run id, nor a word without digits inside a run id?

    A `#` in a word is any one digit, a `~` up to three characters that are neither letters
    nor digits, or none (`status~5##` is `"status": 503` too), and `…` joins parts that each
    stand on their own, in that order on one line, at most 80 characters apart.
    """
    parts = [part.strip() for part in word.split("…")]
    if not all(parts):
        return False
    pattern = ".{0,80}".join(
        (r"(?<!\w)(?<!\d\.)" if re.match(r"[\w#]", part) else "")
        + re.escape(part).replace(r"\#", r"\d").replace(r"\~", r"[\W_]{0,3}")
        + (r"(?!\w)(?!\.\d)" if re.search(r"[\w#]$", part) else "")
        for part in parts)
    matches = list(re.finditer(pattern, text, re.I))
    if not matches:
        return False
    # Paths and file names with their rotation and line references (`run.log.429`,
    # `run.py:429:7`, a traceback's `", line 429`), and ak's run and job ids (a date-time
    # stamp, then words) join numbers with punctuation too. A match of a word with digits
    # stands unless every number in it sits inside one: `HTTP/1.1 429`, `HTTP-503` and
    # `Error-429` are still the status. A word without digits stands unless the whole match
    # sits inside a run or job id as ak makes it -- the stamp, then the slug's letters and
    # digits joined by hyphens (`run.slugify`) -- which names every run's worktree and
    # directory, so a worker naming its own paths (`wt/20261005-0626-fix-agentkit-quota-wait`)
    # says no limit. Each kind is found on its own and every span counts, so one never cuts
    # another short.
    digits = re.search(r"[\d#]", word)
    kinds = ((r'''(?:[^\s"'`{}<>,:;|]*/[^\s"'`{}<>,:;|]*|(?:[A-Za-z]:\\|\\\\)[^\s"'`{}<>,:;|]*)(?::\d+)*''',
              r"\b\w+(?:[-.]\w+)*\.[A-Za-z]\w*(?:[-.]\w+)*\b(?::\d+)*",
              r"\b\d{8}-\d{4,6}(?:-[\w.]+)+", r'(?<=", )line \d+') if digits else
             (r"\b\d{8}-\d{4,6}(?:-[a-z0-9]+)+",))
    ignored = [span.span() for kind in kinds for span in re.finditer(kind, text)]

    def stands(match):
        inner = ([(match.start() + number.start(), match.start() + number.end())
                  for number in re.finditer(r"\d+", match.group())] if digits else [match.span()])
        return not all(any(start <= first and last <= end for start, end in ignored)
                       for first, last in inner)

    return any(stands(match) for match in matches)


def limited(text):
    """Does `text` say a rate limit (`LIMITS`), whole?"""
    return any(says(text, word) for word in LIMITS)


def model_report(conversation):
    """The model, effort and time of that conversation's last changed status render."""
    if not conversation:
        return None
    try:
        with (config.STATE / f"model-{conversation}.json").open() as stream:
            report = json.load(stream)
            # Read the timestamp from the same inode: another render may have replaced it.
            at = os.fstat(stream.fileno()).st_mtime
        if isinstance(report, dict) and isinstance(report.get("model"), str) and report["model"]:
            return report["model"], report.get("effort"), at
    except (OSError, ValueError):
        pass
    return None


def last_entry(path, pick):
    """The last line of that JSON-lines file `pick` takes, read back from its end, or None.

    A conversation's file grows for as long as the conversation does, and a tick wants only
    its last event: a line still being written, or one that is not JSON, is passed over.
    """
    with open(path, "rb") as fh:
        end, rest = fh.seek(0, 2), b""
        while end:
            start = max(0, end - 65536)
            fh.seek(start)
            lines = (fh.read(end - start) + rest).split(b"\n")
            rest = lines.pop(0) if start else b""     # the head of a line the next read ends
            for line in reversed(lines):
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and pick(entry):
                    return entry
            end = start
    return None


# Every reader here takes a record it cannot read for one that holds nothing, except inside
# `strictly`: there, a record that is there and cannot be read is an error (`unread`).  The done
# check reads so, since an owner it could not read is no owner who said nothing.  It is one read
# of them, too: what any of its readers parsed, the next one asking takes (`once`).
_STRICT = contextvars.ContextVar("strict", default=None)     # inside it, {key: what was parsed}


@contextlib.contextmanager
def strictly():
    held = _STRICT.set({})
    try:
        yield
    finally:
        _STRICT.reset(held)


def unread(exc):
    """Raise `exc`, a record failing to read, inside `strictly`, unless it says the record is
    not there: a record that is gone holds nothing either way."""
    if _STRICT.get() is not None and not isinstance(exc, FileNotFoundError):
        raise exc


def once(key, parse):
    """`parse()`; inside `strictly`, what it gave the first reader there asking for `key`, so only
    read."""
    found = _STRICT.get()
    if found is None:
        return parse()
    if key not in found:
        found[key] = parse()
    return found[key]


def _names(path):
    """The names a record is read by, in order: its path, or a list of them, as for one that
    has a second name ak gave it (`claude.kept`)."""
    return path if isinstance(path, list) else [path]


def _opened(path):
    """That record open to read, by the first of its names there as it is opened, so one going
    between finding it and opening it is read by the next; FileNotFoundError where none is."""
    *first, last = _names(path)
    for name in first:
        try:
            return open(name, "rb")
        except FileNotFoundError:
            continue
    return open(last, "rb")


def entries(path):
    """Complete JSON objects in a growing record, by its first name there (`_opened`); an
    unfinished last line can wait."""
    if not path:
        return
    try:
        yield from objects(path)
    except FileNotFoundError:
        return


def objects(path):
    """`entries`, but FileNotFoundError where none of the record's names is there."""
    with _opened(path) as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                yield entry


def turns(path, prompt, answer):
    """That JSON-lines record's messages as `said` gives them, oldest first: a line `prompt`
    reads is the user side's, one `answer` reads the model's, by its first name there
    (`_opened`).  None where no record is there."""
    if not path or not any(Path(name).is_file() for name in _names(path)):
        return None
    said = []
    for entry in entries(path):
        for who, read in (("user", prompt), ("model", answer)):
            text = read(entry)
            if text:
                said.append({"who": who, "text": text})
                break
    return said


def rows(path, query, *args):
    """What `query` reads from that SQLite store, opened read-only: a harness's own database,
    which ak never writes.  None where there is none, or it cannot be read (`unread`)."""
    if not Path(path).exists():
        return None
    try:
        with contextlib.closing(sqlite3.connect(f"{Path(path).absolute().as_uri()}?mode=ro",
                                                uri=True)) as db:
            return db.execute(query, args).fetchall()
    except sqlite3.Error as exc:
        unread(OSError(f"cannot read {path}: {exc}"))
        return None


def moment(at):
    """That time in seconds since the epoch -- a number, or an ISO 8601 time with its zone --
    or None where it is neither."""
    if isinstance(at, str):
        try:
            stamp = datetime.fromisoformat(at)
        except ValueError:
            return None
        at = stamp.timestamp() if stamp.tzinfo else None
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
        return None
    return at


def token_family(paths, roots, metadata):
    """Find descendants from small session headers, never scanning other sessions' messages."""
    children, found, pending = {}, {}, list(roots)
    for path in paths:
        try:
            with path.open("rb") as source:
                session, parent = metadata(json.loads(source.readline()))
            found[session] = path
            children.setdefault(parent, []).append(session)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    seen = set()
    while pending:
        session = pending.pop()
        if session not in seen:
            seen.add(session)
            pending.extend(children.get(session, ()))
    return [found[session] for session in seen if session in found]


def issued(name, conversation, **fields):
    """Write down the launcher's own id as what that launch owns, beside `fields`."""
    config.update_session(name, conversation=conversation, resumable=bool(conversation),
                          id_source=LAUNCHER if conversation else None, before=None, **fields)


@contextlib.contextmanager
def claims():
    """Held while a seat claims a conversation (`claim`) and while a seat is renamed
    (`orch.rename`): two claiming one would each see it free, and a claim names its seat."""
    with (config.STATE / "conversations.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        yield


def claim(launched, harness, conversation, transcript, filed, pid, is_client, **fields):
    """The seat launched as `launched`, on `harness`, goes on in that conversation, `fields`
    beside it, where a hook whose parent is `pid` reported it with `transcript`: only from the
    seat's own interactive process (`orch.owns_hook`, by `is_client`), with that conversation's
    own file for the seat (`filed`), and no other seat's record naming it (`named_elsewhere`), as
    the records stand once no seat learns one meanwhile (`Harness.learning`).  The one its
    harness says the seat is in (`Harness.conversation`) goes into its record first, whether the
    seat moves or not: a harness that learns it from evidence this very prompt moves on (a
    launch's receipt, the database its agy holds open) may not have written it there yet.  Left,
    that one stays the seat's for its done check (`notify.conversations_of`); one it goes back to
    is its current one again, read once.  A seat in none yet, or only in another seat's, takes
    this one as its first; one in a conversation its harness cannot resume stays there.  No
    seat's lock, which a delivery holds while it types the very prompt a hook may report: the
    seat's name holds under `claims` instead."""
    from .. import notify, orch
    if (os.environ.get("AK_RUN_ROLE") == "worker" or not isinstance(conversation, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", conversation) or conversation.startswith("-")
            or not isinstance(transcript, str)):
        return
    if config.session_records().get(config.resolve_session(launched), {}).get(
            "conversation") == conversation:
        return      # the seat's already: decided without waiting on a rename
    with claims():
        name = config.resolve_session(launched)
        record, plugin = config.session_records().get(name, {}), load(harness)
        if orch.seat_harness(record) != harness or not record.get("cwd"):
            return
        current = plugin.conversation(record, record["cwd"])
        current = None if current in named_elsewhere(config.session_records(), name) else current
        if current and not plugin.resumable(record, record["cwd"], current):
            return
        if current and record.get("conversation") != current:
            record = config.update_session(name, conversation=current) or record
        if (record.get("conversation") == conversation
                or Path(transcript).resolve() != Path(filed(record, conversation)).resolve()):
            return
        session = orch.find(name)
        if not session or not orch.owns_hook(session, pid, is_client):
            return
        with plugin.learning():
            if conversation in named_elsewhere(config.session_records(), name):
                return
            left = [was for was in notify.left(record, harness, current)
                    if was["conversation"] not in (conversation, None)]   # none to leave yet
            while (config.update_session(name, conversation=conversation, left=left, **fields)
                   is None and config.resolve_session(name) != name):
                name = config.resolve_session(name)     # moved meanwhile: written where it went


def recorded_conversations(record):
    """Ids already proven by a seat record; `owned` must neither discover nor claim one."""
    return [record.get("conversation"), *(module.owned(record) for module in _plugins("owned"))]


def named_elsewhere(records, name):
    """Each conversation a seat record other than `name`'s names, as its own or as one it left:
    never that seat's to claim or learn."""
    return {conversation for other, record in records.items() if other != name
            for conversation in (*recorded_conversations(record),
                                 *(was.get("conversation") for was in record.get("left") or ()
                                   if isinstance(was, dict)))}


def user_message(at, text):
    """Keep the recorded text and time, never inventing either for a notice."""
    if not isinstance(text, str) or not text:
        return None
    at = moment(at)
    return None if at is None else {"at": at, "text": text}


def prompt(entry):
    """The owner's words one transcript line holds, or None for bookkeeping, injected rules,
    a tool result or anything else: whichever harness wrote it says so in its module's
    `prompt`, and no two write the same shape."""
    for module in _plugins("prompt"):
        said = module.prompt(entry)
        if said is not None:
            return said
    return None


def reported_tokens(out):
    """Kept turn usage, including a plugin's session store when events carry no counters."""
    from .. import history
    out = Path(out)
    total = history.event_tokens(out / "events.jsonl")
    if total is None:
        for module in _plugins("tokens"):
            total = module.tokens(out)
            if total is not None:
                break
    return total


def turn_token_counts(run_dir):
    """Kept event files mapped to (reported usage, turn spend) by their harness."""
    return {path: (total, spent) for module in _plugins("token_counts")
            for path, total, spent in module.token_counts(run_dir)}


def config_entries():
    """Where each harness keeps the trust and MCP entries agentkit writes for it, as
    [{"file": its config, read as JSON or TOML by its suffix, "trust": the table of trusted
    directories, "mcp": the table of MCP servers}], from every plugin that keeps any.
    `ak gc` prunes the entries naming a gone sandbox or checkout."""
    return [module.config_entries() for module in _plugins("config_entries")]


def conversation_stores():
    """Where each harness keeps conversations nothing else ends, as [{"harness": its name,
    "root": a folder, "pattern": the glob under it, at its depth, of one conversation's file or
    folder, "id": a regex that name fullmatches, its first group the conversation's id,
    "names": how many names one's file may have, 1 unless the store says}], from every plugin
    that keeps any, each in as many folders as it keeps.  `ak gc` ends one nobody wrote to for
    30 days, as Claude Code ends its own, unless a seat holds it."""
    return [{"harness": module.__name__.rpartition(".")[2], "names": 1, **store}
            for module in _plugins("conversation_stores") for store in module.conversation_stores()]


def idle_conversations(before):
    """Each conversation a harness keeps as rows of its own database and never ends itself, as
    [{"harness": its name, "id": its id}]: a top-level one nobody updated since `before` (Unix
    seconds), which takes its children along when it ends."""
    return [{"harness": module.__name__.rpartition(".")[2], "id": conversation}
            for module in _plugins("idle_conversations")
            for conversation in module.idle_conversations(before)]


def end_conversation(harness, path, ends):
    """End the conversation that file, or that id of `idle_conversations`, keeps, the harness's
    own way, with whatever it indexed of it, only if `ends(*its other parts)` holds once
    nothing of it can change before it goes.  True where an id's conversation went."""
    return _module(harness).end_conversation(path, ends)


@functools.cache
def _plugins(hook):
    """Every plugin module beside this file that answers `hook`.  Found in this package, not
    the adapter directories, so `ak gc`'s planning, which reads only what it plans for, can ask."""
    modules = (_module(path.stem) for path in sorted(Path(__file__).resolve().parent.glob("*.py")))
    return tuple(module for module in modules if hasattr(module, hook))


def _module(name):
    """`agentkit/harness/<name>.py`, or None where that harness brings no Python.

    Only a plain file beside this one, named exactly for the harness, is imported: a harness
    name is a path component and never a dotted import path, so nothing else can be reached
    from here.
    """
    if not isinstance(name, str) or not config.HARNESS.fullmatch(name):
        return None
    if not (Path(__file__).resolve().parent / f"{name}.py").is_file() or not name.isidentifier():
        return None
    try:
        return importlib.import_module(f".{name}", __name__)
    except ImportError:
        return None


class Harness:
    """One harness's hooks, each answered by its module or by the default beside it.

    The manifest is read on every access rather than remembered, because `config.manifest`
    already caches it by mtime and an adapter toml that changes must show up on the next draw.
    """

    def __init__(self, name):
        self.name = name
        self.module = _module(name)

    def _section(self, table, defaults):
        block = config.manifest(self.name).get(table)
        return {**defaults, **(block if isinstance(block, dict) else {})}

    def _hook(self, name):
        return getattr(self.module, name, None)

    # --- the adapter manifest's own words ---------------------------------

    @property
    def update(self):
        """Its `[update]` table: the commands that move it, and what it cannot put back."""
        return self._section("update", UPDATE)

    @property
    def usage(self):
        """Its `[usage]` table: a captured probe, a stripped timestamp, a spendable reset."""
        facts = self._section("usage", USAGE)
        facts["none"] = bool(facts.get("none"))
        return facts

    @property
    def plans(self):
        """Its `[plans]` table: each plan its `login-end` names, in those words, at its list
        price in US dollars a month."""
        return self._section("plans", {})

    def lost(self, said):
        """Whether a failed turn's own output says the harness holds no such conversation: its
        `[stall]` `lost` words, as `failure` reads the others."""
        block = config.manifest(self.name).get("stall")
        listed = block.get("lost") if isinstance(block, dict) else None
        return any(isinstance(word, str) and says(said, word) for word in listed or ())

    def failure(self, said, ran=True):
        """What a failed turn's own output says, in its `[stall]` words: (outcome, word).

        `said` is the harness's own -- its stderr, its failure events, a final.md nothing
        answered (`turns.harness_said`), a seat's error line -- never the model's answer, and a
        word counts only standing on its own (`says`).  A spent window (`quotas`) outranks a
        refusal (`refusals`), and a refusal an outage (`outages`); where every quota word said
        is only a rate limit (`limited`), the window is LIMITED rather than SPENT, with the
        same first word.  In a turn that never `ran` -- it left no answer at all -- a `faults`
        word says the harness could not run it, and that outranks the rest, unless an outage
        word says the provider was down beside it.  (None, None) where it said none of them.
        """
        def first(key):
            return next(self._heard(key, said), None)

        outage = self.outage(said)
        fault = None if ran or outage else first("faults")
        quotas = list(self._heard("quotas", said))
        spent = LIMITED if all(limited(word) for word in quotas) else SPENT
        for outcome, word in ((FAULT, fault), (spent, quotas[0] if quotas else None),
                              (REFUSAL, first("refusals")), (OUTAGE, outage)):
            if word:
                return outcome, word
        return None, None

    def outage(self, said):
        """The `[stall] outages` word that output says, or None: the provider was down, whatever
        else it says beside that."""
        return next(self._heard("outages", said), None)

    def _heard(self, key, said):
        block = config.manifest(self.name).get("stall")
        listed = block.get(key) if isinstance(block, dict) else None
        words = (listed if isinstance(listed, list) else []) + list(STALL.get(key, ()))
        return (word for word in words if isinstance(word, str) and says(said, word))

    @property
    def conversation_facts(self):
        return self._section("conversation", {"fresh_words": "", "always_offered": False})

    @property
    def fresh_words(self):
        """What a seat starting without a past is said to be doing, in this harness's words."""
        return self.conversation_facts.get("fresh_words") or FRESH_WORDS

    @property
    def always_offered(self):
        """Whether a seat of this harness keeps its row after tmux has lost it.

        True where ownership is decided by evidence outside the record -- a launch receipt --
        so a row has to be recomputed rather than read, and a seat that owns nothing is still
        offered, under its own name, starting fresh.
        """
        return bool(self.conversation_facts.get("always_offered"))

    # --- the conversation a seat holds ------------------------------------

    def seat_auth(self, account):
        """Whether this account can open a seat, including logins only seats support."""
        hook = self._hook("seat_auth")
        if hook:
            return hook(account)
        from .. import worker
        return worker.auth_ok(self.name, seat=True, account=account)

    def checked(self, account):
        """What a launch on that login checks before its adapter is asked, refusing it with a
        `config.Error`; the env pairs that tell the adapter it is done, so the adapter starts
        nothing to do it again.  By default nothing."""
        hook = self._hook("checked")
        return hook(account) if hook else {}

    def conversation(self, record, cwd=None):
        """The conversation this seat owns: by default the one its record was launched with."""
        hook = self._hook("conversation")
        return hook(record, cwd) if hook else record.get("conversation")

    def learning(self):
        """Held while this harness learns which conversation a seat owns (`conversation`), and
        while a seat claims one (`claim`), so neither takes one the other is taking: by default
        it learns none, and nothing is held."""
        hook = self._hook("learning")
        return hook() if hook else contextlib.nullcontext()

    def claim(self, record, cwd=None):
        """(The conversation `conversation` gives while each file its proof reads is as it is
        now, those files): claimed, the proof not made, for a harness whose proof reads the
        conversation itself, as Codex's reads its rollout's first line.  By default what
        `conversation` gives, and no file."""
        hook = self._hook("claim")
        return hook(record, cwd) if hook else (self.conversation(record, cwd), [])

    def resumable(self, record, cwd, conversation):
        """Whether that conversation may be resumed: by default only a launcher-issued id."""
        hook = self._hook("resumable")
        if hook:
            return bool(hook(record, cwd, conversation))
        return bool(conversation) and record.get("id_source") == LAUNCHER

    def restart_word(self, record):
        """Why a row restarts instead of resuming, or None where it has no words for it."""
        hook = self._hook("restart_word")
        return hook(record) if hook else None

    def switchable(self, model, effort):
        """Whether its running seat takes `model` at `effort` from its `[switch]` lines, rather
        than only from a launch: by default it does."""
        hook = self._hook("switchable")
        return hook(model, effort) if hook else True

    def reconcile(self, record):
        """The record fields to write down before anything claims this seat is resumable.

        By default a conversation the launcher did not hand out is not this seat's to resume,
        and is dropped rather than offered.
        """
        hook = self._hook("reconcile")
        if hook:
            return hook(record)
        return ({"conversation": None, "resumable": False}
                if record.get("conversation") and record.get("id_source") != LAUNCHER else {})

    def launched(self, name, cwd, conversation):
        """Write down what this launch owns; the env pairs its command has to carry.

        By default the launcher's own id is the record, and the command needs nothing.
        """
        hook = self._hook("launched")
        if hook:
            return hook(name, cwd, conversation)
        issued(name, conversation)
        return {}

    def follow(self, launched, payload, pid):
        """The seat goes on in the conversation its own process went to, as that hook's payload
        says (`claim`); by default it stays on the one it was launched on."""
        hook = self._hook("follow")
        if hook:
            hook(launched, payload, pid)

    def title_command(self, name):
        """The line that changes a seat's launch title, or None for a harness without one."""
        hook = self._hook("title_command")
        return hook(name) if hook else None

    def sync_title(self, name, record):
        """Set a title without typing: True once confirmed, False pending, None unsupported."""
        hook = self._hook("sync_title")
        return hook(name, record) if hook else None

    @property
    def prompt_hook(self):
        """Its manifest's `UserPromptSubmit` event, or None: the hook that reports each prompt
        as it is sent, the owner's answer to a question among them."""
        events = (config.manifest(self.name).get("hooks") or {}).get("event") or ()
        return next((event for event in events
                     if isinstance(event, dict) and event.get("name") == "UserPromptSubmit"), None)

    @property
    def prompt_context(self):
        """Does what its `UserPromptSubmit` hook prints as `hookSpecificOutput.additionalContext`
        reach the model with that prompt (`context` on that event in its manifest)?"""
        return (self.prompt_hook or {}).get("context") is True

    def context_fits(self, text):
        """Does `text` reach the model whole from its prompt hook: no longer than `context_limit`
        on that event, counted in UTF-16 code units as Claude Code counts it?  Where none is
        declared, any length does."""
        limit = (self.prompt_hook or {}).get("context_limit")
        return limit is None or len(text.encode("utf-16-le")) // 2 <= limit

    @property
    def title_facts(self):
        """The original title-hook contract; adapters can require a stored receipt instead."""
        return self._section("title", {"at_launch": True, "unreadable": True})

    def title_ready(self, record, state):
        """May this owned conversation accept a title now, including a retry?"""
        hook = self._hook("title_ready")
        return hook(record, state) if hook else True

    def session_title(self, record):
        """The latest custom title, empty if absent, or None if the record cannot be read."""
        hook = self._hook("session_title")
        return hook(record) if hook else None

    def forget(self, record):
        """Drop whatever else this harness kept for a seat that is ending."""
        hook = self._hook("forget")
        if hook:
            hook(record)

    def retire(self, record):
        """Drop that launch's receipt alone: the one a started launch replaced, or one whose
        harness never started.  The seat goes on, so nothing else it kept goes."""
        hook = self._hook("retire")
        if hook:
            hook(record)

    def opened(self, cwd, conversation):
        """Has the harness written that conversation down yet?

        Not a question of whose conversation it is -- the launcher settled that -- only of
        whether there is one to resume.  A store nothing here knows is taken at its word.
        """
        hook = self._hook("opened")
        return bool(hook(cwd, conversation)) if hook else True

    def transcript(self, record, cwd, conversation):
        """Where that conversation's transcript is, for a model taking the seat over.

        A path the new orchestrator can read the last exchange from, or None where this
        harness keeps no file to read -- its session lives in a store, or it starts fresh.
        """
        hook = self._hook("transcript")
        return hook(record, cwd, conversation) if hook else None

    def keep(self, record, cwd, conversation):
        """Give that conversation's own file, where its harness deletes it in time, a second
        name of ak's that outlives it.  The tick's alone (`watch.keep_conversations`), so no
        two readers race to give one."""
        hook = self._hook("keep")
        if hook and conversation:
            hook(record, cwd, conversation)

    def said(self, record, cwd, conversation):
        """That conversation as {who: "user" or "model", text}, oldest first, read from the
        harness's own store each time: what the user side typed, ak included, and the model's
        visible answers, never tool calls or results, thinking, subagents, compaction summaries
        or protocol frames.  None where this harness keeps nothing ak can read."""
        hook = self._hook("said")
        return hook(record, cwd, conversation) if hook else None

    def read_by(self, record, cwd, conversation):
        """The names of the one file that conversation's messages and answers are read from, in
        the order its readers try them (`entries`), none where it has no file yet.  None where
        its harness keeps it in no file of its own, as in a database, or names none."""
        hook = self._hook("read_by")
        if not hook:
            return None
        names = hook(record, cwd, conversation)
        return _names(names) if names else []

    @property
    def reads_messages(self):
        """Whether it can say which messages of a conversation are the owner's (`user_messages`)."""
        return self._hook("user_messages") is not None

    def user_messages(self, record, cwd, conversation, *, seat=None):
        """Owner messages, oldest first, as {at: Unix seconds, text: original words}.

        The plugin rejects its own synthetic input. The seat's typing receipts remove
        ak's input, a line each at most, in whichever of the seat's conversations it went into
        (`notify.conversations_of`): the one it names, else the first after it in another, as
        a screen showing another than the seat's record names takes it (`grokbuild.follow`).
        Relayed owner replies and identical later prompts stay.
        A native answer may include `replies`, the opaque ids of the questions it answers.
        """
        hook = self._hook("user_messages")
        if not hook:
            return []
        said = {conversation: sorted(hook(record, cwd, conversation),
                                     key=lambda message: message["at"])}
        if not seat:
            return said[conversation]
        from .. import notify
        seat = config.resolve_session(seat)
        for plugin, *was in notify.conversations_of(seat):
            if plugin.name == self.name and was[-1] not in said:
                try:
                    said[was[-1]] = self.user_messages(*was)
                except (OSError, ValueError) as exc:
                    unread(exc)     # this one's own words still read
        # every line, oldest first, a conversation's own in its order; lines of two at one time
        # by their conversations' names, so a receipt takes the same whichever is read
        lines = sorted(((message["at"], into, index) for into, messages in said.items()
                        for index, message in enumerate(messages)),
                       key=lambda line: (line[0], str(line[1])))
        taken, excluded = set(), set()
        for sent in entries(config.seat_file("input", seat)):
            if sent.get("harness") != self.name:
                continue
            named = self.went_into(sent)
            # another only where the one it names was read: one the seat no longer holds, or
            # that cannot be read, may hold its line
            fits = [(into, index) for at, into, index in lines
                    if (into, index) not in taken and said[into][index]["text"] == sent.get("text")
                    and (index >= sent.get("after", math.inf) if into == named
                         else named in said and at >= sent.get("at", math.inf))]
            # the first in the conversation it names, else the first after it
            line = min(fits, key=lambda fit: fit[0] != named, default=None)
            if line:
                taken.add(line)
                if sent.get("source") != "owner":
                    excluded.add(line)
        return [message for index, message in enumerate(said[conversation])
                if (conversation, index) not in excluded]

    def receipt(self, record, conversation, text, source="ak"):
        """The typing receipt `user_messages` tells that line by, written before it goes into
        that seat's conversation: the messages already there are `after` it.  Where its harness
        has not named that conversation yet, as on a fresh Codex launch, it keeps what that
        launch wrote in the record (`launch`), by which the harness names it once it has."""
        sent = {"at": time.time(), "text": text, "source": source, "harness": self.name,
                "conversation": conversation,
                "after": len(self.user_messages(record, record.get("cwd"), conversation))}
        if conversation is None:
            sent["launch"] = {key: record[key] for key in LAUNCH_KEYS
                              if record.get(key) is not None}
        return sent

    def went_into(self, sent):
        """The conversation a receipt's line went into: the one it names, else the one its
        launch's own evidence reported (`receipt`), however far its harness has moved that
        launch on since, as Muse's `/new` does (its module's `reported`); None while that names
        none."""
        launch = sent.get("launch")
        if sent.get("conversation") or not isinstance(launch, dict):
            return sent.get("conversation")
        reported = self._hook("reported")
        return reported(launch) if reported else self.conversation(launch)

    def answers(self, record, cwd, conversation):
        """Each question the owner answered on its own question card, oldest first, as {at,
        question, choices: [{label, description}], answer}: the answer in the owner's words as
        the harness recorded it, the question and choices in the seat's.  Unless its module
        reads them, none; nor one with no answer, or with any part of it not text."""
        hook = self._hook("answers")
        return [answer for answer in hook(record, cwd, conversation) if all(
            isinstance(text, str) for text in (answer["question"], answer["answer"], *(
                text for choice in answer["choices"]
                for text in (choice["label"], choice["description"]))))
            and answer["answer"].strip()] if hook else []

    def error(self, record, cwd, conversation):
        """The error the harness recorded as that conversation's last event: the text it showed,
        and any kind it typed apart from that text.

        "" where the conversation went on after it, None where no record exists; OSError where
        one exists and cannot be read.  Only what it said: what it means is `failure`'s and the
        `[auth]` words' to say, as for a screen's error line.
        """
        hook = self._hook("error")
        return hook(record, cwd, conversation) if hook else None

    def interrupted(self, record, cwd, conversation):
        """When the owner interrupted that conversation's turn, where the harness recorded it as
        the last event -- an end it reports by no hook -- or None.  OSError where a record
        exists and cannot be read."""
        hook = self._hook("interrupted")
        return hook(record, cwd, conversation) if hook else None

    def wrapped_up(self, record, cwd, conversation):
        """When the harness told that conversation's turn its usage limit was reached and to stop
        -- an end that refuses nothing -- where no prompt came after it, or None.  OSError where
        a record exists and cannot be read."""
        hook = self._hook("wrapped_up")
        return hook(record, cwd, conversation) if hook else None

    def card(self, record, cwd):
        """Its harness's own question card in the conversation that seat owns, as the hook fact
        {event, kind, text, at} its going up or its settling writes, or None.  OSError where a
        record exists and cannot be read."""
        hook = self._hook("card")
        return hook(record, cwd, self.conversation(record, cwd)) if hook else None

    def unanswered(self, record, cwd, conversation):
        """The owner's prompt that is that conversation's last message, as {at, text}, or None:
        one nothing has answered or interrupted yet.  OSError where a record exists and cannot
        be read."""
        hook = self._hook("unanswered")
        return hook(record, cwd, conversation) if hook else None

    def running(self, record, cwd, conversation):
        """(model id, effort, when) last recorded for that conversation by its harness
        -- the effort None where it records none, when in seconds since the epoch (moment)
        -- or None where it records neither.  OSError where a record exists and cannot be read."""
        hook = self._hook("running")
        return hook(record, cwd, conversation) if hook else None

    def holds(self, record):
        """The type of each piece of background work that seat's harness says it runs now, in
        `held_work`'s terms, or None where it cannot be asked: its last Stop's list stands."""
        hook = self._hook("holds")
        return hook(record) if hook else None

    @property
    def keeps_errors(self):
        """Whether `error` reads anything: a transcript alone may hold no error a reader knows."""
        return self._hook("error") is not None

    # --- what its own installation and usage call know --------------------

    def identity(self, text, argv):
        """Its `[update] version` output as a build identity, refined where it has more to say."""
        hook = self._hook("identity")
        return hook(text, argv) if hook else text

    def snapshots(self):
        """Whether an upgrade of it is put back from a local snapshot it takes itself (`snapshot`).

        False by default: its `[update] revert` puts it back, or nothing can.
        """
        return self._hook("snapshot") is not None

    def snapshot(self, harness, identity, version):
        """Its installed build, saved and verified before `ak update` moves it: a context
        manager whose `restore()` puts it back.  Only for a harness that `snapshots()`.

        `harness` is its `ak update` plan entry, `identity` the build installed now and
        `version(harness)` how `ak update` reads the installed identity.
        """
        return self._hook("snapshot")(harness, identity, version)

    def usage_extra(self, out, data, state_dir):
        """After a usage probe: whatever else this harness knows about what it just said."""
        hook = self._hook("usage_extra")
        if hook:
            hook(out, data, state_dir)

    def usage_recorded(self, state_dir, now):
        """Meters this harness wrote down itself -- a refused run's quota -- still standing, or []."""
        hook = self._hook("usage_recorded")
        return hook(state_dir, now) if hook else []

    def usage_policy(self, entry, effort):
        """Whether that config.toml entry is a probe of this harness's own to run.

        False by default: a harness with no probe of its own has no policy to satisfy.
        """
        hook = self._hook("usage_policy")
        return bool(hook(entry, effort)) if hook else False

    def mode(self, entry):
        """`subscription` or `payg` where the harness's own config says how that model is paid.

        None by default: config.toml's `[providers.*] mode` stands.
        """
        hook = self._hook("mode")
        return hook(entry) if hook else None

    def tmp_rule(self, table):
        """A temp rule for this process inventory, or None when the harness owns no folder.

        The rule takes (path, now, paths, top): None means unowned; otherwise it
        returns (removal reason, nested candidates). A missing reason keeps the path.
        """
        hook = self._hook("tmp_rule")
        return hook(table) if hook else None

    def register_mcp(self, servers):
        """Point this harness at `servers` in its own config, as `ak browser mcp-register`
        does: what it did and where, or None where its plugin writes no MCP entry.

        `servers` is {name: {"url": …}} for a server by URL and {name: {"command", "args",
        "env"}} for one it starts itself.
        """
        hook = self._hook("register_mcp")
        return hook(servers) if hook else None

    # --- what seats and headless turns spent ---------------------------------

    def seat_token_sources(self, record):
        """Usage logs for this seat and its children; None means no reader is available."""
        hook = self._hook("seat_token_sources")
        return hook(record) if hook else None

    def seat_token_usage(self, entry, cursor):
        """One log entry's (time, unique event id, tokens, model, [input, cache write, cache
        read, output]), model and counts None where unknown; or None.  cursor survives readings."""
        hook = self._hook("seat_token_usage")
        return hook(entry, cursor) if hook else None

    def record_turn(self, out, state_dir, account):
        """Import this harness's reports after the box closes, without exposing ak's records."""
        hook = self._hook("record_turn")
        if hook:
            hook(Path(out), state_dir, account)

    def tokens(self, out):
        """The tokens the turn written to `out` spent, or None where this harness said nothing.

        By default they are in the event log its adapter wrote there; a harness that keeps
        them elsewhere reads them from there.
        """
        hook = self._hook("tokens")
        if hook:
            return hook(Path(out))
        from .. import history   # here, not at the top: history is what reads this
        return history.event_tokens(Path(out) / "events.jsonl")

    def turn_usage(self, out):
        """(the session holding the turn's usage, None where none does; whether its counts
        total that session rather than count this turn alone; {model: (input, cache write, cache
        read, output)}) the turn written to `out` reported, the model None where it named none;
        None where it reported none, as by default.
        """
        hook = self._hook("turn_usage")
        return hook(Path(out)) if hook else None

    def turn_meters(self, out):
        """The meters the turn in `out` reported about its own account, or [].

        By default a harness reports none: only one that prints its account's limits in
        its stream has anything to say, and what it says is endpoint-shaped meters.
        """
        hook = self._hook("turn_meters")
        if hook:
            return hook(Path(out))
        return []

    def status_meters(self, windows):
        """The meters a seat's status render said of its own account, each window as the words
        its status hook printed (`watch.hook_meters`), or []: by default a status line says none."""
        hook = self._hook("status_meters")
        return hook(windows) if hook else []


def load(name):
    """The plugin for that harness: its module's hooks where it has them, defaults elsewhere.

    Kept per name, because the module is all it holds: the manifest behind every fact it
    answers is read through `config.manifest`, which rereads a toml the moment it changes.
    """
    key = name if isinstance(name, str) else ""
    if key not in _LOADED:
        _LOADED[key] = Harness(name if isinstance(name, str) else None)
    return _LOADED[key]
