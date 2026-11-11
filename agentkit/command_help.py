"""Public command help, safe to print before importing operational command modules."""

import os

from . import config

WORKER_USAGE = ("usage: ak worker MODEL TASK [--workspace DIR] [--out DIR] [--session ID]\n"
                "       [--role executor|reviewer|fixer|reviewer-pr|executor-scratch|"
                "fixer-scratch|reviewer-scratch]")
NOTIFY_NEEDS = 'ak notify needs "QUESTION" [--session NAME] [--dry-run]'
NOTIFY_USAGE = f"usage: {NOTIFY_NEEDS}\n       ak notify --check"
HAND_IN_FINDING = 'ak hand-in finding PATH:LINE "WHAT" "WHY IT MATTERS" (--run COMMAND | --quote LINES)'
HAND_IN_FOLLOWUP = 'ak hand-in follow-up PATH:LINE "WHAT" "WHY IT MATTERS" (--run COMMAND | --quote LINES) [--before PROOF]'
HAND_IN_DISPUTE = 'ak hand-in dispute PATH:LINE "WHY IT IS WRONG" (--run COMMAND | --quote LINES)'
HAND_IN_CONCEDE = 'ak hand-in concede PATH:LINE "WHY"'

# Each entry is (usage, description, example). Model selections remain in config.toml;
# MODEL in usage/examples stands for one of that file's keys.
COMMANDS = {
    "models": ("usage: ak models [--json] [--refresh]",
               "Say what each role of the seat it runs in, else new seats, uses, and draw each\n"
               "role's choices as bars, as the models screen does, then ak's own run numbers:\n"
               "Artificial Analysis and Arena, each asked once a day; --refresh asks now, --json\n"
               "prints each role's best and its line of best quality for the money, with ak's\n"
               "own numbers.",
               "ak models"),
    "usage": ("usage: ak usage [--json]", "Show provider usage and worker pick order.",
              "ak usage --json"),
    "worker": (WORKER_USAGE, "Run one headless model turn from a task or prompt file.",
               "ak worker MODEL task.md --role reviewer"),
    "hand-in": (f"usage: {HAND_IN_FINDING}\n       {HAND_IN_FOLLOWUP}\n       {HAND_IN_DISPUTE}\n       {HAND_IN_CONCEDE}\n       ak hand-in done\n"
                '       ak hand-in blocked "WHY"\n       ak hand-in not-needed "WHY"',
                "Hand in review evidence or close a worker turn.\n"
                "The loop names AK_HAND_IN; outside a turn this command is refused.\n"
                "Paths and lines must exist in the checkout; a quote must occur in that file.\n"
                "--run executes in the checkout and records bounded output excerpts and the exit status.\n"
                "A finding's command must fail while the defect exists; ak re-runs it on commit and base.\n"
                "A follow-up from before the task has --before, naming the base or an ancestor commit, or verbatim lines in its file at base; its command must fail on base.\n"
                "A follow-up of this change has no --before; its --run must fail now and on the reviewed commit.\n"
                "Unproven follow-ups are dropped into Notes.\n"
                "A follow-up's --run is one line without backticks or this checkout's path.\n"
                "Only a fixer may dispute a blocking finding handed to its turn; its command must exit 0.\n"
                "ak gives the next reviewer the dispute and its own proof output beside the finding.\n"
                "Answer every dispute: hand the finding in again to uphold it, or concede its site with why.\n"
                "A review's done waits until every handed dispute has an answer.\n"
                "done closes any turn; in a review, any blocking finding means FAIL, otherwise PASS.\n"
                "Executors and fixers use blocked when the task cannot be done as written, or\n"
                "not-needed when a fix run's first turn finds the defect gone or already being fixed.\n"
                "Review turns refuse blocked and not-needed; other turns refuse finding and follow-up.\n"
                "A closing record refuses later records.",
                'ak hand-in finding api.py:12 "Wrong result" "Breaks callers" --quote "return None"'),
    "hand-in finding": (f"usage: {HAND_IN_FINDING}",
                        "Hand in a finding for ak to weigh, with a failing command or quoted evidence.",
                        'ak hand-in finding api.py:12 "Wrong result" "Breaks callers" --run "python3 reproduce.py"'),
    "hand-in follow-up": (f"usage: {HAND_IN_FOLLOWUP}",
                          "Hand in a defect that cannot fail this review: one that existed before the task (--before proves it),\n"
                          "or a smaller one of this change that need not hold it (no --before; --run must fail now).\n"
                          "Its command becomes the check of a line in the owning session's plan, deferred once a fix run of its own has it.",
                          'ak hand-in follow-up api.py:12 "Wrong result" "Breaks callers" --run "python3 reproduce.py" --before "return None"'),
    "hand-in dispute": (f"usage: {HAND_IN_DISPUTE}",
                        "Dispute a blocking finding handed to this fixer, with a passing command or quoted evidence.",
                        'ak hand-in dispute api.py:12 "The result is correct" --run "python3 check_result.py"'),
    "hand-in concede": (f"usage: {HAND_IN_CONCEDE}",
                        "Accept a dispute handed to this reviewer and record why it is right.",
                        'ak hand-in concede api.py:12 "The default is required"'),
    "hand-in done": ("usage: ak hand-in done", "Close this worker turn; a review derives its verdict.",
                     "ak hand-in done"),
    "hand-in blocked": ('usage: ak hand-in blocked "WHY"',
                        "End an executor or fixer run whose task cannot be done as written.",
                        'ak hand-in blocked "The task requires an unavailable file"'),
    "hand-in not-needed": ('usage: ak hand-in not-needed "WHY"',
                           "End a fix run on its first turn if its defect is gone or already being fixed.",
                           'ak hand-in not-needed "The target already fixes empty input"'),
    "run": ("""usage: ak run TASK [TASK ...] [--rounds N] [--exec MODEL] [--review MODEL]
              [--anyway] [--first] [--no-worktree] [--no-merge] [--bg] [--parallel N]
              [--in-order]
       ak run --review-pr URL [--review MODEL] [--first] [--no-merge] [--bg]
       ak run status [ID] [--history] [--why] [--plain] [--json] [--tests]
       ak run resume ID [--rounds N] [--bg]
       ak run stop ID [--keep]
       ak run merge ID | ak run clean ID | ak run gc [--dry-run]""",
            """Execute, verify, review, push, open a PR and merge.
$run_budget
--anyway starts even when a run in the same repository looks already under way;
$rounds_refusal
--no-worktree uses the repo's current branch; --no-merge keeps work local.
--bg detaches and prints a launch receipt, run ID and result path.
--first admits the run ahead of every queued run without it, skipping the count cap and a pinned load gate; a heavy suite turn still goes by wait.
From a seat, --exec, --review, --anyway and --first are refused: ak picks the models,
decides what goes first and refuses a second run of a change under way.
Several task files run as one job of independent pieces; --parallel caps it.
--in-order starts each task once the one before it merged, and none after one that did not.
max_runs caps the count when positive; 0 leaves host memory as the gate
(config.toml or AK_MAX_RUNS).
$pr_delivery
Task size: $executor_size.
Seat's work: $orchestrator_size.
Task fields: repo, base, target, from, merge (squash|merge|rebase), rounds.""",
            "ak run task.md --bg"),
    "run status": ("usage: ak run status [ID] [--history] [--why] [--plain] [--json] [--tests]",
                   "Show current work and result paths; --history includes older runs.\n"
                   "--tests alone audits this checkout's test times, flakes, catches and main reds\n"
                   "over its retained rows, proposing splits and fixes or deletions.",
                   "ak run status --history --json"),
    "run resume": ("usage: ak run resume ID [--rounds N] [--bg]",
                   "Resume interrupted or exhausted work; $resume_budget",
                   "ak run resume RUN_ID$resume_example --bg"),
    "run merge": ("usage: ak run merge ID",
                  "Retry delivery of a finished PASS; reverify if integration changes its commit.",
                  "ak run merge RUN_ID"),
    "run stop": ("usage: ak run stop ID [--keep]",
                 "Stop a run or a whole job deliberately; --keep keeps its worktree and branch for a from: relaunch.",
                 "ak run stop RUN_ID"),
    "run clean": ("usage: ak run clean ID", "Remove a run's worktree.", "ak run clean RUN_ID"),
    "run gc": ("usage: ak run gc [--dry-run]",
               "Collect inactive temporary state and old merged checkouts; --dry-run only plans.",
               "ak run gc --dry-run"),
    "orch": ("""usage: ak orch [NAME] [--model MODEL] [--workers A,B] [--dry-run]
       ak orch list [--why] | ak orch why NAME | ak orch check SEAT | ak orch look FILE
       ak orch stop NAME | ak orch rename [--auto] [OLD] NEW
       ak orch project [SEAT] CHECKOUT | ak orch rules CODE | ak orch pair SEAT""",
             "Start or attach to a named orchestrator session; a new one opens only from a terminal.\n"
             "--dry-run prints the launch plan.",
             "ak orch parser-fix"),
    "orch rules": ("usage: ak orch rules CODE",
                   "Say this seat's conversation read the rulebook file its prompt named,\n"
                   "with the code on that file's last line: its prompts stop naming it until it changes.",
                   "ak orch rules 3f2a9c81d0e4"),
    "orch pair": ("usage: ak orch pair SEAT",
                  "Print a code that pairs the provider's app with a Codex seat; it pages nobody.\n"
                  "SEAT is the seat's name, a name it had, or the path of its home.",
                  "ak orch pair parser-fix"),
    "orch list": ("usage: ak orch list [--why]",
                  "List orchestrator sessions and their selections;\n"
                  "--why adds what decided each seat's state, on what evidence, and since when.",
                  "ak orch list --why"),
    "orch why": ("usage: ak orch why NAME",
                 "Explain one seat's state: the authority, the rule or hook event,\n"
                 "the evidence line and when that state began.",
                 "ak orch why parser-fix"),
    "orch check": ("usage: ak orch check SEAT",
                   "Ask one model whether a seat's work holds everything its owner asked of it.\n"
                   "Exits 1 naming each gap in the owner's words, 0 with none, 2 if it could not check.",
                   "ak orch check parser-fix"),
    "orch look": ("usage: ak orch look FILE",
                  "Keep a picture of a screen this seat's work changed, an image or a text capture\n"
                  "of a terminal screen, as it is now: its done check sees each one kept.",
                  "ak orch look chart.png"),
    "orch stop": ("usage: ak orch stop NAME",
                  "Stop a session and keep it, its number reopening it; stop it again to remove it.",
                  "ak orch stop parser-fix"),
    "orch rename": ("usage: ak orch rename [--auto] [OLD] NEW",
                    "Rename a session; omit OLD to rename the session this runs in.\n"
                    "--auto names only an unnamed seat; an already named seat is left alone.",
                    "ak orch rename parser-fix parser-review"),
    "orch project": ("usage: ak orch project [SEAT] CHECKOUT",
                     "File a seat under a checkout by name or path; omit SEAT for this session.\n"
                     "Only known checkouts are accepted; it stays there until it is filed again.\n"
                     "Then lists what the project's other sessions have in flight: their open\n"
                     "plan lines and the files their going runs change.",
                     "ak orch project acme"),
    "notify": (NOTIFY_USAGE,
               "Record a needs-you question.\n"
               "--session and --dry-run apply to needs; --check checks without posting.",
               'ak notify needs "Which branch?" --session parser-fix --dry-run'),
    "notify needs": (f"usage: {NOTIFY_NEEDS}",
                     "Ask for a blocking decision: the question first, context after it.\n"
                     "--dry-run prints the payload without posting.",
                     'ak notify needs "Which branch?" --session parser-fix --dry-run'),
    "wait": ("usage: ak wait PR_URL|RUN_ID",
             "End this turn waiting on that pull request or run; ak wakes you with one line\n"
             "when it merges, closes or ends. One already over is refused. Never a session.",
             "ak wait https://github.com/acme/api/pull/12"),
    "plan": ("usage: ak plan | ak plan add \"OUTCOME\" --check 'COMMAND' | "
             "ak plan check N 'COMMAND'",
             "This session's plan: each line an outcome with the check that proves it.\n"
             "add runs the check on the project's default branch and refuses one that passes,\n"
             "does not finish or holds the project's checkout path (it runs in a clean one);\n"
             "check N puts your own test in place of line N's check, such as a review\n"
             "follow-up's probe; it must fail on the commit the line names, where its check failed.\n"
             "Listing ticks each check line that now passes on its project's default branch;\n"
             "with every line ticked, a model checks the work against what the owner asked,\n"
             "and with nothing missing the session's work is done.",
             "ak plan add \"each session sees its project\" --check 'python3 tests/test_x.py'"),
    "update": ("usage: ak update [--dry-run]",
               "Upgrade harnesses and verify with acceptance gates; --dry-run prints the plan.",
               "ak update --dry-run"),
    "watch": ("usage: ak watch [--dry-run]",
              "Check PRs and stalled sessions; --dry-run lists what a tick would do.",
              "ak watch --dry-run"),
    "browser": ("usage: ak browser <status|login|mcp-register|install>",
                "Inspect the shared browser, sign in, register MCP tools, or install the stack.",
                "ak browser status"),
    "browser status": ("usage: ak browser status",
                       "Show units, CDP, open tabs, the desktop and the noVNC URL.",
                       "ak browser status"),
    "browser login": ("usage: ak browser login",
                      "Show the noVNC URL and password to sign a site in by hand.",
                      "ak browser login"),
    "browser mcp-register": ("usage: ak browser mcp-register",
                             "Register browser and desktop MCP servers with every harness that can take them.",
                             "ak browser mcp-register"),
    "browser install": ("usage: ak browser install",
                        "Install the stack if absent; verify an existing installation.",
                        "ak browser install"),
    "doctor": ("usage: ak doctor",
               "Show the agents' slice, the tick's state, each machine ak may use, and any\n"
               "model set to an effort it does not take, which it names and never changes,\n"
               "then the best machine to rent from Google Cloud now, or why there is none.\n"
               "Says `no slice` where the machine has no user systemd manager.\n"
               "Exits 1 when no tick has ended for long enough to call the tick hung.",
               "ak doctor"),
    "attach": ("usage: ak attach [--client] [--overlay] [--dry-run]",
               "Open the session menu (also: ak). --client stays on this host;\n"
               "--overlay opens the menu inside a seat; --dry-run prints planned actions.",
               "ak attach --client"),
    "fetch": ("usage: ak fetch PATH [PATH ...] | ak fetch --serve",
              "Copy requested Mac files to this host; --serve handles the Mac bridge connection.\n"
              "Use -- before paths to request a file named -h or --help.",
              "ak fetch /Users/me/Desktop/report.pdf"),
    "macbridge": ("usage: ak macbridge [--reader]", "macOS only: forward requested files to the server over SSH.\n"
                  "--reader starts a detached reader under this terminal app for dropped files.",
                  "ak macbridge"),
    "move": ("usage: ak move ALIAS",
             "Copy this home to the same path on the machine `ssh ALIAS` reaches; run again, it\n"
             "sends only what changed and deletes there what was deleted here.  Each machine keeps\n"
             "its own of ak's tmp folder, ~/.ssh/authorized_keys and the browser profile's locks.\n"
             "Refused if ALIAS is this machine, its home has another path, its crontab holds ak's\n"
             "tick or fails, or one of those kept is a link or under one on either machine.",
             "ak move acme-mini"),
}


# `ak --help` is one screen: the menu, then the commands an orchestrator uses, one line
# each, and under one dim `internal:` line the ones the toolkit runs for itself.
ORCHESTRATOR = ("run", "plan", "notify", "wait", "usage", "models", "browser", "fetch")
INTERNAL = ("orch", "worker", "hand-in", "watch", "update", "macbridge", "attach", "doctor", "move")

PURPOSES = {
    "run": "execute a task file to a merged PR",
    "plan": "show or write this session's checked plan",
    "orch": "open a seat",
    "worker": "run one headless model turn from a task or prompt file",
    "hand-in": "hand in review evidence or close a worker turn",
    "attach": "the menu",
    "usage": "show provider usage and worker pick order",
    "models": "score every model and effort per role from the public boards, recommend one per role",
    "browser": "inspect the shared browser, sign in, register MCP tools, or install the stack",
    "update": "upgrade harnesses and verify with acceptance gates",
    "watch": "check PRs and stalled sessions",
    "doctor": "show the slice, the tick, the machines, and any model set to an effort it does not take",
    "notify": "record a needs-you question",
    "wait": "end this turn waiting on a pull request or run",
    "fetch": "copy requested Mac files to this host",
    "macbridge": "macOS only: forward requested files to the server over SSH",
    "move": "copy this home to the same path on another machine",
}


def purpose(command, table=None):
    """The command's one-line purpose: the top table's for a top-level command,
    otherwise its description's first line."""
    if command in PURPOSES:
        return PURPOSES[command]
    return config.in_force(COMMANDS[command][1].splitlines()[0], table)


def _same_sentence(first, second):
    """Whether two purpose lines say the same sentence: case, a trailing full
    stop and surrounding space never distinguish them."""
    return first.strip().rstrip(".").lower() == second.strip().rstrip(".").lower()


def render(command):
    if not command:
        # terminal here and not at the top: help is printed before any operational module
        # is imported, and terminal.py is layout only
        from . import terminal
        width = max(len(name) for name in ORCHESTRATOR)
        lines = ["usage: ak [command]", "", f"  {'ak'.ljust(width)}  {PURPOSES['attach']}"]
        lines += [f"  {name.ljust(width)}  {PURPOSES[name]}" for name in ORCHESTRATOR]
        lines += ["", terminal.styled("internal:  " + "  ".join(INTERNAL), "dim"), ""]
        return "\n".join(lines) + "\nUse -h or --help after any command.\nExample: ak run task.md --bg\n"
    numbers = None
    if os.environ.get(config.SESSION_ENV):
        try:
            seat = config.session_record(config.current_session()) or {}
            numbers = config.policy(seat.get("repo", seat.get("cwd")))
        except config.Error:
            pass        # help still prints when a seat or its settings cannot be read
    usage, description, example = (config.in_force(text, numbers) for text in COMMANDS[command])
    # the one-line purpose first, then the usage and the rest of the
    # description as today: a description that opens by repeating the purpose
    # keeps only the purpose line, never the same sentence twice
    lines = description.splitlines()
    said = purpose(command, numbers)
    if lines and _same_sentence(lines[0], said):
        description = "\n".join(lines[1:])
    body = f"{said}\n\n{usage}"
    if description:
        body += f"\n\n{description}"
    return body + f"\n\nExample: {example}\n"


def show(command, argv):
    """Handle help anywhere before --, choosing a recognized leading nested verb."""
    args = argv[:argv.index("--")] if "--" in argv else argv
    if not any(arg in ("-h", "--help") for arg in args):
        return False
    nested = f"{command} {args[0]}" if args else command
    print(render(nested if nested in COMMANDS else command), end="")
    return True
