"""`ak orch check SEAT`: does the seat's work hold everything its owner said to it?

One model's one turn, as `ak worker` runs one, under the reviewer's scratch role, in a workspace
of its own holding what the seat was asked and what it did: each message its owner wrote it
(`notify.owner_messages`, ak's own lines left out) and each answer they gave on its question
cards beside the question and choices it wrote (`answers`), oldest first, one file each, in
each conversation it had, those it left included (`notify.conversations_of`); each of those
conversations as its harness keeps it (`said`), so a "yes" reads against what the seat proposed
and a question against the seat's reply; its plan; each run it launched; and each picture of a
screen it kept with `ak orch look` (`look`), so a screen the owner will see reads as it was kept,
on every harness alike, never as the seat says it is.  The model
hands in each gap as a finding quoting the owner.  A quote that is not word for word in one
message or answer of the owner's is no gap, whatever the model wrote in its workspace, the seat's
replies, questions and choices included: that is decided here, not by the model.  Exit 1 with a
gap, 0 with none, and 2 (an Error) where nothing could be checked.

A check that finds no gap keeps what it read (`keep`), and one that finds a gap forgets it: a
seat whose plan has every line done owes a check (`owed`) until one read what its owner has said
and its plan holds now.
"""

import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import (command_help, config, hand_in, harness, notify, plan, record, staffing, transitions,
               worker)

ASK = """\
# Does seat {name}'s work hold everything its owner asked of it?

{workspace} holds the seat's record:
- owner/: each message its owner wrote to it, and each answer they gave on its question
  cards after the question and choices it wrote, a file each, oldest first from 1.md.
- conversation.md: each conversation it had as its harness keeps it, oldest first, a `---`
  line where one was left for the next. The user side holds ak's lines as well as the owner's:
  only owner/ says which words are the owner's.
- plan.md: its plan, `- [x]` a line done and `- [ ]` one open.
- runs/: each run it launched: its title, state, whether it merged, its PR and its task.
- pictures/: each picture of a screen it kept with `ak orch look`, an image or a text capture
  of a terminal screen, as the screen was then, oldest first:
{pictures}

Read each message of the owner's where it stands in the conversation: a "yes" or "the second
one" takes what the seat proposed just before. A gap is something the owner asked to be built or
changed that no done plan line and no merged run delivered; a screen the owner will see that the
work changed and no picture shows, quoting the ask that changed it; or a question or a request to
explain that no reply of the seat's answered. Only a later message of the owner's drops or changes
an ask; the seat's replies never do.

Hand in each gap as `ak hand-in finding owner/N.md:LINE "what the work does not hold" "why the
owner needs it" --quote "the owner's words"`, the words copied exactly from that message or
answer. Here the quote is what makes a finding a gap, never a note: ak keeps each gap the owner's
own words hold and drops every other. Then `ak hand-in done`, with gaps or with none.
"""

# what a seat owes while its plan's every line is done and no check found that it holds
# everything its owner said, as `stop.owed_line` names it
OWED = "a check of its finished plan against what its owner said"


def on(cfg):
    """`[done_check] on`, true unless written false: off, a finished plan owes no check.  It
    reads `on` alone, so a `model` the config no longer has never holds a seat the check is off
    for."""
    table = cfg.get("done_check")
    return not (isinstance(table, dict) and table.get("on") is False)


def setting(cfg):
    """`[done_check]` as `c`'s `Done check` page and `checker` read it: `on` (on) and `model`,
    the model that makes the check, None for the seat's reviewer.  A value config.toml holds that
    neither can take is an Error naming it, so the page and `ak orch check` say the same."""
    table = cfg.get("done_check", {})
    if not isinstance(table, dict):
        raise config.Error(f"~/.agentkit/{config.CONFIG_NAME}: [done_check] must be a table")
    if not isinstance(table.get("on", True), bool):
        raise config.Error(f"~/.agentkit/{config.CONFIG_NAME}: [done_check].on must be true or "
                           f"false (got {table['on']!r})")
    named = table.get("model")
    if named is not None:
        if not isinstance(named, str):
            raise config.Error(f"~/.agentkit/{config.CONFIG_NAME}: [done_check].model must be a "
                               f"model name (got {named!r})")
        config.model(cfg, named)
    return {"on": on(cfg), "model": named}


def owed(name, text):
    """Whether the seat, its plan `text` holding lines and every one done, owes a done check:
    one is on, the owner wrote a message or answered a question card in one of its
    conversations, and no check that found no gap read what they have said and what the plan
    holds now (`fingerprint`).  A record ak cannot read holds the seat.  Their words are read only
    for such a plan, and only where what an answer was kept from changed since (`asked`): ak asks
    for every seat it draws.  Nothing here makes a check."""
    if not any(plan.BOX.match(line) for line in text) or any(plan.is_open(line) for line in text):
        return False
    try:
        if not on(config.load()):
            return False
        with harness.strictly():
            seats = notify.conversations_of(name)
            try:
                kept = config.seat_file("checked", name).read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                kept = None
            read, path = asked(name, seats, text, kept), config.seat_file("owed", name)
            if read and (was := answered(path)).get("read") == read:
                return was["owed"]
            owner = owner_words(name, seats)
    except (OSError, ValueError, config.Error):
        return True
    answer = bool(owner) and fingerprint(owner, text) != kept      # none with no conversation
    if read:
        # whole, by a name of this ask's own: of two asks at once, either may stand
        fresh = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}")
        try:
            fresh.write_text(json.dumps({"read": read, "owed": answer}) + "\n", encoding="utf-8")
            fresh.replace(path)
        except OSError:
            pass        # a state ak cannot write here: the next ask reads again
    return answer


def asked(name, seats, text, kept):
    """What `owed` answers from, short of the owner's words, as a digest: the plan's `text`, what
    a check `kept`, and the file each of the seat's conversations `seats` is read from, by each
    of its names, with its identity, size and modification time, the seat's typing receipts' too,
    which tell ak's lines in it from the owner's, and the directories of the code that reads
    them, which an update of ak replaces.  Taken before their words are read, so a file written
    meanwhile reads changed next time.  None where a conversation's harness keeps it in no file
    of its own (`Harness.read_by`): that one is read every time."""
    files = [config.seat_file("input", config.resolve_session(name)), Path(__file__).parent,
             Path(harness.__file__).parent]
    conversations = []
    for plugin, record, cwd, conversation in seats:
        names = plugin.read_by(record, cwd, conversation)
        if names is None:
            return None
        conversations.append([plugin.name, conversation])
        files += names
    stamps = []
    for path in files:
        try:
            info = os.stat(path)
            stamps.append([str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns])
        except FileNotFoundError:
            stamps.append([str(path), None])
    return hashlib.sha256(json.dumps([text, kept, conversations, stamps]).encode()).hexdigest()


def answered(path):
    """What an ask of `owed` kept there: its answer and what it read, {} for none."""
    try:
        was = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return was if isinstance(was, dict) else {}


def owner_words(name, seats):
    """The owner's words to seat `name` in its conversations `seats`, oldest first, as (when, the
    words, the file showing them): each message they wrote it and each answer they gave on its
    question cards.  A message that replies to a card (`replies`) counts only as those answers:
    its text repeats the seat's question as if the owner had said it."""
    return sorted([*((message["at"], message["text"], message["text"])
                     for seat in seats for message in notify.owner_messages(name, seat)
                     if "replies" not in message),
                   *((answer["at"], answer["answer"], card(answer))
                     for seat in seats for answer in seat[0].answers(*seat[1:]))],
                  key=lambda said: said[0])


def fingerprint(owner, text):
    """What a check of the owner's words against a plan of `text` read, for a later one to be
    compared with: each word of theirs with when it was said, and the plan's lines without the
    proof stamp a renewed one changes."""
    lines = [plan.undone(line.strip(), found) if (found := plan.LINE.match(line.strip()))
             else line.strip() for line in text if plan.BOX.match(line)]
    read = [[[at, words] for at, words, _ in owner], lines]
    return hashlib.sha256(json.dumps(read).encode()).hexdigest()


def keep(name, read):
    """Keep what a check that found no gap `read`, or, None, forget what one kept: under the
    seat's lock, which a rename takes too, so under the name it goes by now.  Of two checks of
    a seat at once, the one that ends last stands."""
    with notify.session_lock(name) as current:
        path = config.seat_file("checked", current)
        if read is None:
            path.unlink(missing_ok=True)
            return
        fresh = path.with_name(path.name + ".new")
        fresh.write_text(read + "\n", encoding="utf-8")
        fresh.replace(path)


def look(argv):
    """`ak orch look FILE`: keep a picture of a screen the seat's work changed for its done
    check, as the file is now and beside every one kept before, a later one of the same file
    included.  The seat's, as its plan is: under its lock, which a rename takes too, so under the
    name it goes by now, and no conversation's."""
    if len(argv) != 1:
        raise config.Error(command_help.COMMANDS["orch look"][0])
    seat = config.current_session()
    if not seat:
        raise config.Error("ak orch look belongs to a session; run it inside one")
    path = Path(argv[0])
    try:
        kept = json.dumps({"at": time.time(), "name": path.name,
                           "data": base64.b64encode(path.read_bytes()).decode()}) + "\n"
        with notify.session_lock(config.resolve_session(seat)) as current:
            # written whole beside the pictures, then in their place: a write cut short leaves
            # them as they were, never a torn line the next one is appended to
            pictures = config.seat_file("pictures", current)
            fresh = pictures.with_name(pictures.name + ".new")
            fresh.write_bytes((pictures.read_bytes() if pictures.exists() else b"") + kept.encode())
            fresh.replace(pictures)
    except OSError as exc:
        raise config.Error(f"cannot keep {argv[0]}: {exc.strerror}") from None
    print(f"{current}'s done check will see {path.name} as it is now")
    return 0


def checker(cfg, name):
    """`[done_check] model` (setting), else the reviewer a run of that seat's would draw now."""
    named = setting(cfg)["model"]
    if named:
        return named
    order = staffing.ready_order(cfg, staffing.collect_usage(cfg),
                                 config.reviewers(cfg, name), role="reviewer", quiet=True)
    if not order:
        raise config.Error(f"none of {name}'s reviewers can run now")
    return order[0]


def card(answer):
    """An answer's file: the question and choices the seat wrote, then the owner's answer."""
    return "".join([f"The seat asked on its question card: {answer['question']}\n",
                    *(f"- {choice['label']}"
                      + (f": {choice['description']}" if choice["description"] else "") + "\n"
                      for choice in answer["choices"]),
                    f"\nThe owner answered:\n{answer['answer']}\n"])


def gaps(cfg, name):
    """The findings of the checking turn that quote one of the owner's messages or answers.
    What it read is kept where it found none (`keep`); one that found a gap or could not check
    forgets what an earlier one kept, counting for nothing."""
    read = None
    try:
        with harness.strictly():
            seats = notify.conversations_of(name)
            if not seats:
                raise config.Error(f"no seat named {name} whose conversation ak can read")
            owner = owner_words(name, seats)
            pictures = [*harness.entries(config.seat_file("pictures", name))]
        said = [words for _, words, _ in owner]
        if not said:
            return []       # asked nothing, so nothing is missing
        planned = plan.lines(name)
        model = checker(cfg, name)
        print(f"ak orch check: {model} reads what {name} was asked and did", file=sys.stderr)
        config.ensure_dirs()
        with tempfile.TemporaryDirectory(prefix=f"check-{name}-", dir=config.TMP) as tmp:
            workspace, out = Path(tmp, "workspace"), Path(tmp, "out")
            files = {f"owner/{n}.md": shown for n, (_, _, shown) in enumerate(owner, 1)}
            files["conversation.md"] = "---\n\n".join(
                "".join(f"**{turn['who']}:** {turn['text']}\n\n"
                        for turn in seat[0].said(*seat[1:]) or []) for seat in seats)
            files["plan.md"] = "".join(line + "\n" for line in planned)
            shown = []
            for n, picture in enumerate(pictures, 1):
                # numbered, never named: a name the filesystem took leaves no room for more;
                # its type stays for the reader, the name itself in the list
                kept = f"pictures/{n}{Path(picture['name']).suffix[:16]}"
                files[kept] = base64.b64decode(picture["data"])
                shown.append(f"  - {kept}: {picture['name']}, kept "
                             + time.strftime(plan.STAMP, time.localtime(picture["at"])))
            for directory, state in record.runs():
                if transitions.launched_session(state) == name:
                    task = directory / "task.md"
                    files[f"runs/{directory.name}.md"] = (
                        f"title: {state.get('title')}\nstate: {state.get('state')}\n"
                        f"merged: {'yes' if state.get('merged') else 'no'}\n"
                        f"PR: {state.get('pr') or 'none'}\n\n"
                        + (task.read_text(errors="replace") if task.is_file() else ""))
            for relative, text in files.items():
                (workspace / relative).parent.mkdir(parents=True, exist_ok=True)
                (workspace / relative).write_bytes(text if isinstance(text, bytes)
                                                   else text.encode())
            try:
                # an existing role, which Go's rules already hold: the reviewer's of a
                # workspace, whose hand-in takes findings and refuses a quote its file does
                # not hold
                worker.turn(cfg, model, ASK.format(name=name, workspace=workspace,
                                                   pictures="\n".join(shown) or "  none kept"),
                            workspace, out, role="reviewer-scratch")
            except worker.LoginExpired as expired:
                raise config.Error(str(expired)) from None
            review = hand_in.read(out / hand_in.FILE)
        if not review or not review.done:
            raise config.Error(f"{model} could not check {name}: its turn did not end in "
                               "`ak hand-in done`")
        found = [row for row in review.findings
                 if (quote := row["evidence"].get("quote", "")).strip()
                 and any(quote in text for text in said)]
        read = None if found else fingerprint(owner, planned)
        return found
    finally:
        keep(name, read)


def main(argv):
    if len(argv) != 1:
        raise config.Error("usage: ak orch check SEAT")
    name = config.resolve_session(argv[0])
    # a record ak cannot read leaves the seat unchecked, exit 2: an uncaught one would exit 1,
    # which says a gap
    try:
        found = gaps(config.load(), name)
    except (OSError, ValueError) as exc:
        raise config.Error(f"could not check {name}: {exc}") from None
    if not found:
        print(f"{name}: its work holds everything its owner asked")
        return 0
    print(f"{name}: {len(found)} thing{'s' if len(found) > 1 else ''} its owner asked "
          "not in its work")
    for row in found:
        print(f"- {row['what']}\n  the owner: \"" + row["evidence"]["quote"].replace("\n", "\n  ")
              + '"')
    return 1
