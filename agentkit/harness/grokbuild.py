"""Grok Build's shared settings, launcher-issued conversation followed to each session its own
process runs a prompt in, pinned session title and the sessions nobody wrote to for 30 days."""

import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib
from urllib.parse import quote

from .. import config
from . import LAUNCHER

SOURCE = "grokbuild-hook"   # `id_source`: a session the seat's own Grok ran a prompt in (`follow`)
# An answered `ask_user_question` card's result, around the owner's answers (`given`).
ANSWERED = ("User has answered your questions: ",
            ". You can now continue with the user's answers in mind.")


def share_settings(usual, directory):
    """Keep credentials private while every login uses the usual user preferences.

    Grok Build 1.0.46's bundled Configuration guide names these two files. Its user
    config writer follows leaf symlinks, unlike its project config writer. Checked
    in a temporary HOME with user-scoped MCP saves, /vim-mode, and /settings'
    Respect manual folds toggle (which saves pager.toml): both links survive.
    """
    from ..config import _toml_key, _toml_value

    def fill(shared, own):
        changed = False
        for key, value in own.items():
            if key not in shared:
                shared[key] = value
                changed = True
            elif isinstance(shared[key], dict) and isinstance(value, dict):
                changed = fill(shared[key], value) or changed
        return changed

    usual, directory = Path(usual).resolve(), Path(directory)
    # Serialize first launches across logins without creating another state file.
    lock = os.open(usual, os.O_RDONLY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name in ("config.toml", "pager.toml"):
            source, link = usual / name, directory / name
            if link.is_symlink() and link.resolve() == source.resolve():
                continue
            if link.exists():
                own_text = link.read_text()
                own = tomllib.loads(own_text)
                target = source.resolve()
                if target.exists():
                    shared = tomllib.loads(target.read_text())
                    changed = fill(shared, own)
                    text = "".join(f"{_toml_key(key)} = {_toml_value(value)}\n"
                                   for key, value in shared.items()) if changed else None
                else:
                    text = own_text
                if text is not None:
                    tomllib.loads(text)
                    fd, temporary = tempfile.mkstemp(dir=target.parent)
                    temporary = Path(temporary)
                    try:
                        with os.fdopen(fd, "w") as handle:
                            handle.write(text)
                        if target.exists():
                            temporary.chmod(target.stat().st_mode & 0o777)
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
            link.unlink(missing_ok=True)
            link.symlink_to(source)
    finally:
        os.close(lock)


def session_dir(cwd, conversation):
    home = Path(os.environ.get("GROK_HOME") or Path.home() / ".grok")
    return home / "sessions" / quote(str(cwd), safe="") / str(conversation)


def follow(launched, payload, pid):
    """A prompt the seat's own Grok ran in another session than its record's moves the seat
    there (`claim`), whoever typed it: in 1.0.46 only a prompt names the session /new, Ctrl+N or
    /dashboard went to, so every session the seat ran one in stays its own, read whichever its
    words landed in, and the last is the one its screen showed last."""
    from .. import orch
    from . import claim
    if isinstance(payload, dict) and payload.get("hook_event_name") == "UserPromptSubmit":
        claim(launched, "grokbuild", payload.get("session_id"), payload.get("transcript_path"),
              lambda record, session: session_dir(record["cwd"], session) / "updates.jsonl",
              pid, lambda words: orch.program(words) == "grok", id_source=SOURCE)


def resumable(record, cwd, conversation):
    """A session the launcher issued, or one the seat's own Grok ran a prompt in (`follow`)."""
    return bool(conversation) and record.get("id_source") in (LAUNCHER, SOURCE)


def reconcile(record):
    return ({"conversation": None, "resumable": False}
            if record.get("conversation") and not resumable(record, None, record["conversation"])
            else {})


def transcript(record, cwd, conversation):
    """The chat history the new orchestrator reads the last exchange from.

    Only where the harness has written one: a conversation nobody typed into has no
    file, and the handover says so instead of pointing at it.
    """
    where = cwd or record.get("cwd")
    if not conversation or not where:
        return None
    path = session_dir(where, conversation) / "chat_history.jsonl"
    return str(path) if path.exists() else None


def running(record, cwd, conversation):
    """Grok Build 1.0.46 saves model and effort changes in summary.json immediately, before
    any answer.  Its write time lets a look leave a summary from before the launch alone."""
    where = cwd or record.get("cwd")
    if not conversation or not where:
        return None
    try:
        with (session_dir(where, conversation) / "summary.json").open(encoding="utf-8") as handle:
            data = json.load(handle)
            model = data.get("current_model_id")
            return ((model, data.get("reasoning_effort"), os.fstat(handle.fileno()).st_mtime)
                    if isinstance(model, str) and model else None)
    except (OSError, ValueError, AttributeError):
        return None


def read_by(record, cwd, conversation):
    """The durable UI record its messages and answers are read from, None where it has none."""
    where = cwd or record.get("cwd")
    return session_dir(where, conversation) / "updates.jsonl" if conversation and where else None


def messages(record, cwd, conversation):
    """The durable UI record's messages, oldest first, as (who, {at, text}), chunks joined and
    host turns, shell commands and other updates left out; it outlives model-context compaction."""
    from . import entries, user_message
    current, key = None, None
    for entry in entries(read_by(record, cwd, conversation)):
        params = entry.get("params")
        params = params if isinstance(params, dict) else {}
        update = params.get("update")
        update = update if isinstance(update, dict) else {}
        meta = update.get("_meta")
        meta = meta if isinstance(meta, dict) else {}
        content = update.get("content")
        content = content if isinstance(content, dict) else {}
        who = {"user_message_chunk": "user", "agent_message_chunk": "model"}.get(
            update.get("sessionUpdate"))
        spoken = (entry.get("method") == "session/update"
                  and params.get("sessionId") == conversation
                  and who and not meta.get("hostTurn"))
        chunk_key = (who, meta.get("promptIndex"), meta.get("interjection", False))
        if current and (not spoken or chunk_key != key or meta.get("interjection")):
            yield key[0], current
            current = None
        if not spoken or content.get("type") != "text":
            continue
        content_meta = content.get("_meta")
        content_meta = content_meta if isinstance(content_meta, dict) else {}
        if content_meta.get("bashCommand") is not None:
            continue
        text = content_meta.get("displayText", content.get("text"))
        kept = user_message(entry.get("timestamp"), text)
        if kept:
            if current:
                current["text"] += kept["text"]
            else:
                current, key = kept, chunk_key
    if current:
        yield key[0], current


def user_messages(record, cwd, conversation):
    return (message for who, message in messages(record, cwd, conversation) if who == "user")


def answers(record, cwd, conversation):
    """Each question the owner answered on an `ask_user_question` card, beside the question and
    options the seat asked with, dated when they submitted the card: its call's `completed`
    update, whose result holds the only record of their answers (`given`).  A dismissed card's
    result is another message, which answers nothing."""
    from . import entries, moment
    asked = {}
    for entry in entries(read_by(record, cwd, conversation)):
        said = []
        try:    # a line of any other shape answers nothing
            params, update = entry["params"], entry["params"]["update"]
            call, at = update["toolCallId"], moment(entry.get("timestamp"))
            if entry["method"] != "session/update" or params["sessionId"] != conversation:
                continue
            if (update["sessionUpdate"] == "tool_call"
                    and update["_meta"]["x.ai/tool"]["name"] == "ask_user_question"):
                asked[call] = update["rawInput"]["questions"]
            elif (update["sessionUpdate"] == "tool_call_update" and call in asked
                  and update["status"] == "completed" and at is not None):
                said = [{"at": at, **answer} for answer in given(
                    asked.pop(call), update["rawOutput"]["UserAnswered"]["message"])]
        except (AttributeError, KeyError, TypeError):
            continue
        yield from said


def given(questions, message):
    """Each of the card's `questions` an answered card's `message` answers, with its choices and
    the owner's answer: the label picked or the labels ticked, then any words typed on a line of
    their own.

    Grok Build 1.0.46 lists the questions answered in the order asked, joined by ", ", each as
    `"<question>"="<chosen>"`, nothing escaped: the label picked, the labels ticked joined by
    ", ", or "Other" where they only typed, then ` user notes: ` and any words typed.  Each
    question is read only with what it offered, so a label, or words typed, holding the
    message's own punctuation, or a question's opening with an answer it did not offer, read
    whole."""
    asked = [(question["question"], [{"label": option["label"],
                                      "description": option.get("description", "")}
                                     for option in question.get("options") or ()])
             for question in questions]
    head, tail = ANSWERED
    body = re.fullmatch(f"{re.escape(head)}(.*){re.escape(tail)}", message, re.S)
    pattern = ""
    for text, choices in asked:     # each question there or not, the first there opening the list
        label = "|".join(re.escape(choice["label"]) for choice in choices)
        pattern += (rf'(?:(?:\A|, )"{re.escape(text)}"="((?:{label})(?:, (?:{label}))*'
                    r'|Other(?=" user notes: ))"(?: user notes: (.*?))?)?')
    found = body and re.fullmatch(pattern, body[1], re.S)
    chosen = found.groups() if found else ()
    for (text, choices), picked, typed in zip(asked, chosen[::2], chosen[1::2]):
        if picked is not None:
            yield {"question": text, "choices": choices, "answer": "\n".join(filter(None, (
                None if picked == "Other" and typed is not None else picked, typed)))}


def said(record, cwd, conversation):
    """Read from the UI record, not chat_history.jsonl: that is the model's context, which a
    compaction rewrites and which wraps every prompt in tags of its own."""
    where = cwd or record.get("cwd")
    if not conversation or not where or not session_dir(where, conversation).is_dir():
        return None
    return [{"who": who, "text": message["text"]}
            for who, message in messages(record, cwd, conversation)]

def opened(cwd, conversation):
    """Has Grok written that conversation down yet, where it keeps them?

    One directory per workspace under its sessions, named for the url-encoded working
    directory, each conversation a directory of its own inside it.  A directory that
    exists is resumed; one that does not is opened fresh under the same id, which is what
    `--session-id` demands: a valid UUID that does not already exist.
    """
    return session_dir(cwd, conversation).is_dir()


def title_command(name):
    return f"/rename {name}"


def title_ready(record, state):
    # A responding turn can queue input. Wait for the prompt, including our held line,
    # and for this conversation's summary to exist before touching the composer.
    return state in ("at_prompt", "draft") and session_title(record) is not None


def session_title(record):
    """Only a manual title in this conversation's summary can name or confirm the seat."""
    conversation, cwd = record.get("conversation"), record.get("cwd")
    if not cwd or not resumable(record, cwd, conversation):
        return None
    try:
        data = json.loads((session_dir(cwd, conversation) / "summary.json").read_text(
            encoding="utf-8"))
        if data.get("info") != {"id": conversation, "cwd": str(cwd)}:
            return None
        if data.get("title_is_manual") is not True:
            return ""
        title = data.get("generated_title")
        return title if isinstance(title, str) and title.strip() else ""
    except (OSError, ValueError, AttributeError):
        return None


def conversation_stores():
    """Each login home's own sessions folder, a folder per session under its url-encoded cwd:
    Grok ends none unless its owner sets `storage.cleanup_ttl_days`.  An account's home links
    its sessions to ~/.grok's unless Grok made the folder first; a linked one is scanned there."""
    from .. import gc
    # tmp_listdir, not glob: planning leaves HOME's atime alone.
    homes = [Path.home() / name for name in (".grok", *(name for name in gc.tmp_listdir(Path.home())
                                                        if name.startswith(".grok-")))]
    return [{"root": home / "sessions", "pattern": "*/*/", "id": re.compile("(.+)")}
            for home in homes if not (home / "sessions").is_symlink()]


def end_conversation(path, ends):
    """`grok sessions delete`, which takes the session's folder and its session_search.sqlite
    row, run on the home that keeps it.  In 1.0.46 it needs no leader, login or answer, and
    takes none of the session's .lock files, so there is no lock to hold first; a session it
    cannot read it reports missing and exits 0, so a folder still there is a failure too."""
    folder = Path(path)
    if not ends():
        return
    subprocess.run([config.harness_binary("grok") or "grok", "sessions", "delete", folder.name],
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
                   env={**os.environ, "GROK_HOME": str(folder.parents[2])}, check=True)
    if folder.exists():
        raise OSError(f"grok sessions delete left {folder}")
