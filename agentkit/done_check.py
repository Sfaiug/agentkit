"""`ak orch check SEAT`: does the seat's work hold everything its owner said to it?

One model's one turn, as `ak worker` runs one, under the reviewer's scratch role, in a workspace
of its own holding what the seat was asked and what it did: each message its owner wrote it,
oldest first, one file each (`notify.owner_messages`, ak's own lines left out); its plan; and
each run it launched.  The model hands in each gap as a finding quoting the owner.  A quote that
is not word for word in one message of the owner's is no gap, whatever the model wrote in its
workspace: that is decided here, not by the model.  Exit 1 with a gap, 0 with none, and 2 (an
Error) where nothing could be checked.
"""

import sys
import tempfile
from pathlib import Path

from . import config, hand_in, notify, plan, record, staffing, transitions, worker

ASK = """\
# Does seat {name}'s work hold everything its owner asked of it?

{workspace} holds the seat's record:
- owner/: each message its owner wrote to it, a file each, oldest first from 1.md.
- plan.md: its plan, `- [x]` a line done and `- [ ]` one open.
- runs/: each run it launched: its title, state, whether it merged, its PR and its task.

A gap is something the owner asked for that no done plan line and no merged run delivered. A
later message of the owner's that drops or changes an ask replaces it.

Hand in each gap as `ak hand-in finding owner/N.md:LINE "what the work does not hold" "why the
owner needs it" --quote "the owner's words"`, the words copied exactly from that message. Here
the quote is what makes a finding a gap, never a note: ak keeps each gap the owner's own words
hold and drops every other. Then `ak hand-in done`, with gaps or with none.
"""


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


def gaps(cfg, name):
    """The findings of the checking turn that quote one of the owner's messages."""
    seat = notify.conversation_of(name)
    if seat is None or not seat[3]:
        raise config.Error(f"no seat named {name} whose conversation ak can read")
    said = [message["text"] for message in notify.owner_messages(name, seat, strict=True)]
    if not said:
        return []       # asked nothing, so nothing is missing
    model = checker(cfg, name)
    print(f"ak orch check: {model} reads what {name} was asked and did", file=sys.stderr)
    config.ensure_dirs()
    with tempfile.TemporaryDirectory(prefix=f"check-{name}-", dir=config.TMP) as tmp:
        workspace, out = Path(tmp, "workspace"), Path(tmp, "out")
        files = {f"owner/{n}.md": text for n, text in enumerate(said, 1)}
        files["plan.md"] = "".join(line + "\n" for line in plan.lines(name))
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
            # an existing role, which Go's rules already hold: the reviewer's of a workspace,
            # whose hand-in takes findings and refuses a quote its file does not hold
            worker.turn(cfg, model, ASK.format(name=name, workspace=workspace), workspace, out,
                        role="reviewer-scratch")
        except worker.LoginExpired as expired:
            raise config.Error(str(expired)) from None
        review = hand_in.read(out / hand_in.FILE)
    if not review or not review.done:
        raise config.Error(f"{model} could not check {name}: its turn did not end in "
                           "`ak hand-in done`")
    return [row for row in review.findings
            if (quote := row["evidence"].get("quote", "")).strip()
            and any(quote in text for text in said)]


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
