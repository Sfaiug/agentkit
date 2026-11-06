"""`ak orch check SEAT`: does the seat's work hold everything its owner said to it?

One model's one turn, as `ak worker` runs one, under the reviewer's scratch role, in a workspace
of its own holding what the seat was asked and what it did: each message its owner wrote it
(`notify.owner_messages`, ak's own lines left out) and each answer they gave on its question
cards beside the question and choices it wrote (`answers`), oldest first, one file each; its
whole conversation as its harness keeps it (`said`), so a "yes" reads against what the seat
proposed and a question against the seat's reply; its plan; and each run it launched.  The model
hands in each gap as a finding quoting the owner.  A quote that is not word for word in one
message or answer of the owner's is no gap, whatever the model wrote in its workspace, the seat's
replies, questions and choices included: that is decided here, not by the model.  Exit 1 with a
gap, 0 with none, and 2 (an Error) where nothing could be checked.

A check that finds no gap keeps what it read (`keep`), and one that finds a gap forgets it: a
seat whose plan has every line done owes a check (`owed`) until one read what its owner has said
and its plan holds now.
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from . import config, hand_in, harness, notify, plan, record, staffing, transitions, worker

ASK = """\
# Does seat {name}'s work hold everything its owner asked of it?

{workspace} holds the seat's record:
- owner/: each message its owner wrote to it, and each answer they gave on its question
  cards after the question and choices it wrote, a file each, oldest first from 1.md.
- conversation.md: its whole conversation as its harness keeps it, oldest first. The user side
  holds ak's lines as well as the owner's: only owner/ says which words are the owner's.
- plan.md: its plan, `- [x]` a line done and `- [ ]` one open.
- runs/: each run it launched: its title, state, whether it merged, its PR and its task.

Read each message of the owner's where it stands in the conversation: a "yes" or "the second
one" takes what the seat proposed just before. A gap is something the owner asked to be built or
changed that no done plan line and no merged run delivered, or a question or a request to explain
that no reply of the seat's answered. Only a later message of the owner's drops or changes an
ask; the seat's replies never do.

Hand in each gap as `ak hand-in finding owner/N.md:LINE "what the work does not hold" "why the
owner needs it" --quote "the owner's words"`, the words copied exactly from that message or
answer. Here the quote is what makes a finding a gap, never a note: ak keeps each gap the owner's
own words hold and drops every other. Then `ak hand-in done`, with gaps or with none.
"""

# what a seat owes while its plan's every line is done and no check found that it holds
# everything its owner said, as `stop.owed_line` names it
OWED = "a check of its finished plan against what its owner said"


def on(cfg):
    """`[done_check] on`, true unless written false: off, a finished plan owes no check."""
    table = cfg.get("done_check")
    return not (isinstance(table, dict) and table.get("on") is False)


def owed(name, text):
    """Whether the seat, its plan `text` holding lines and every one done, owes a done check:
    one is on, the owner wrote a message in its conversation, and no check that found no gap
    read what they have said and what the plan holds now (`fingerprint`).  A record ak cannot
    read holds the seat.  Their words are read only for such a plan; nothing here makes a check."""
    if not any(plan.BOX.match(line) for line in text) or any(plan.is_open(line) for line in text):
        return False
    try:
        if not on(config.load()):
            return False
        with harness.strictly():
            seat = notify.conversation_of(name)
            messages = notify.owner_messages(name, seat)    # none with no conversation
            if not messages:
                return False
            owner = owner_words(seat, messages)
        try:
            kept = config.seat_file("checked", name).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            kept = None
        return fingerprint(owner, text) != kept
    except (OSError, ValueError, config.Error):
        return True


def owner_words(seat, messages):
    """The owner's words to the seat, oldest first, as (when, the words, the file showing them):
    each of its `messages` and each answer they gave on its question cards."""
    return sorted([*((message["at"], message["text"], message["text"]) for message in messages),
                   *((answer["at"], answer["answer"], card(answer))
                     for answer in seat[0].answers(*seat[1:]))], key=lambda said: said[0])


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


def checker(cfg, name):
    """`[done_check] model`, else the reviewer a run of that seat's would draw now."""
    table = cfg.get("done_check")
    named = table.get("model") if isinstance(table, dict) else None
    if named:
        config.model(cfg, named)
        return named
    order = staffing.ready_order(cfg, staffing.collect_usage(cfg),
                                 config.reviewers(cfg, name), role="reviewer", quiet=True)
    if not order:
        raise config.Error(f"none of {name}'s reviewers can run now")
    return order[0]


def card(answer):
    """An answer's file: the question and choices the seat wrote, then the owner's answer."""
    return "".join([f"The seat asked on its question card: {answer['question']}\n",
                    *(f"- {choice['label']}: {choice['description']}\n"
                      for choice in answer["choices"]),
                    f"\nThe owner answered:\n{answer['answer']}\n"])


def gaps(cfg, name):
    """The findings of the checking turn that quote one of the owner's messages or answers.
    What it read is kept where it found none (`keep`); once it has the seat's conversation, one
    that found a gap or could not check forgets what an earlier one kept, counting for nothing."""
    with harness.strictly():
        seat = notify.conversation_of(name)
    if seat is None or not seat[3]:
        raise config.Error(f"no seat named {name} whose conversation ak can read")
    read = None
    try:
        with harness.strictly():
            owner = owner_words(seat, notify.owner_messages(name, seat))
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
            files["conversation.md"] = "".join(f"**{turn['who']}:** {turn['text']}\n\n"
                                               for turn in seat[0].said(*seat[1:]) or [])
            files["plan.md"] = "".join(line + "\n" for line in planned)
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
                (workspace / relative).write_text(text)
            try:
                # an existing role, which Go's rules already hold: the reviewer's of a
                # workspace, whose hand-in takes findings and refuses a quote its file does
                # not hold
                worker.turn(cfg, model, ASK.format(name=name, workspace=workspace), workspace,
                            out, role="reviewer-scratch")
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
