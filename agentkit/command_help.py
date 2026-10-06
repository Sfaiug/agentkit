"""Public command help, safe to print before importing operational command modules."""

WORKER_USAGE = ("usage: ak worker MODEL TASK [--workspace DIR] [--out DIR] [--session ID]\n"
                "       [--role executor|reviewer|fixer|reviewer-pr|executor-scratch|"
                "fixer-scratch|reviewer-scratch]")
NOTIFY_NEEDS = 'ak notify needs "QUESTION" [--session NAME] [--dry-run]'
NOTIFY_DONE = ('ak notify done "SUMMARY" [--pr URL] '
               '[--session NAME] [--dry-run]')
NOTIFY_USAGE = (f"usage: {NOTIFY_NEEDS}\n       {NOTIFY_DONE}\n"
                "       ak notify --check")
HAND_IN_FINDING = 'ak hand-in finding PATH:LINE "WHAT" "WHY IT MATTERS" (--run COMMAND | --quote LINES)'
HAND_IN_FOLLOWUP = 'ak hand-in follow-up PATH:LINE "WHAT" "WHY IT MATTERS" (--run COMMAND | --quote LINES) --before PROOF'
HAND_IN_DISPUTE = 'ak hand-in dispute PATH:LINE "WHY IT IS WRONG" (--run COMMAND | --quote LINES)'

# Each entry is (usage, description, example). Model selections remain in config.toml;
# MODEL in usage/examples stands for one of that file's keys.
COMMANDS = {
    "usage": ("usage: ak usage [--json]", "Show provider usage and worker pick order.",
              "ak usage --json"),
    "worker": (WORKER_USAGE, "Run one headless model turn from a task or prompt file.",
               "ak worker MODEL task.md --role reviewer"),
    "hand-in": (f"usage: {HAND_IN_FINDING}\n       {HAND_IN_FOLLOWUP}\n       {HAND_IN_DISPUTE}\n       ak hand-in done\n"
                '       ak hand-in blocked "WHY"\n       ak hand-in not-needed "WHY"',
                "Hand in review evidence or close a worker turn.\n"
                "The loop names AK_HAND_IN; outside a turn this command is refused.\n"
                "Paths and lines must exist in the checkout; a quote must occur in that file.\n"
                "--run executes in the checkout and records bounded output excerpts and the exit status.\n"
                "A finding's command must fail while the defect exists; ak re-runs it on commit and base.\n"
                "A follow-up's command must run and fail on base; --before names the base or an ancestor commit, or verbatim lines in its file at base.\n"
                "Unproven follow-ups are dropped into Notes.\n"
                "A follow-up's --run is one line without backticks or this checkout's path.\n"
                "Only a fixer may dispute a blocking finding handed to its turn; its command must exit 0.\n"
                "ak gives the next reviewer the dispute and its own proof output beside the finding.\n"
                "Hand the finding in again to uphold it; otherwise it is dropped into result.md's Disputes.\n"
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
                          "Hand in a proven defect that existed before the task; it cannot fail this review.\n"
                          "Its command becomes the check on a line in the plan of the session that owns the work.",
                          'ak hand-in follow-up api.py:12 "Wrong result" "Breaks callers" --run "python3 reproduce.py" --before "return None"'),
    "hand-in dispute": (f"usage: {HAND_IN_DISPUTE}",
                        "Dispute a blocking finding handed to this fixer, with a passing command or quoted evidence.",
                        'ak hand-in dispute api.py:12 "The result is correct" --run "python3 check_result.py"'),
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
       ak run --review-pr URL [--review MODEL] [--first] [--no-merge] [--bg]
       ak run status [ID] [--history] [--why] [--plain] [--json]
       ak run resume ID [--rounds N] [--bg]
       ak run yes ID
       ak run no ID
       ak run stop ID [--keep]
       ak run merge ID | ak run clean ID | ak run gc [--dry-run]""",
            """Execute, verify, review, push, open a PR and merge.
--rounds sets the round limit, at most 3 (default: task rounds or 3).
--anyway starts even when a run in the same repository looks already under way;
a task over 3 rounds is refused regardless.
--no-worktree uses the repo's current branch; --no-merge keeps work local.
--bg detaches and prints a launch receipt, run ID and result path.
--first admits the run ahead of every queued run without it, skipping the count cap and the CPU gate; a heavy suite turn still goes by wait.
Several task files run as one job of independent pieces; --parallel caps it.
max_runs caps the count when positive; 0 leaves host memory and ak's CPU pressure as the gates
(config.toml or AK_MAX_RUNS).
--review-pr reviews a GitHub PR, without an executor: the seat's own merges on
PASS with green checks, anyone else's asks the inbox.
Task fields: repo, base, target, from, merge (squash|merge|rebase), rounds, after.""",
            "ak run task.md --bg"),
    "run status": ("usage: ak run status [ID] [--history] [--why] [--plain] [--json]",
                   "Show current work and result paths; --history includes older runs.",
                   "ak run status --history --json"),
    "run resume": ("usage: ak run resume ID [--rounds N] [--bg]",
                   "Resume interrupted or exhausted work; --rounds raises the round limit, at most 3.",
                   "ak run resume RUN_ID --rounds 3 --bg"),
    "run yes": ("usage: ak run yes ID",
                "The owner's yes to a run's change to their parts (AGENTS.md `owner:`), then its delivery.",
                "ak run yes RUN_ID"),
    "run no": ("usage: ak run no ID",
               "The owner declines a run's change to their parts; the run ends, its branch kept.",
               "ak run no RUN_ID"),
    "run merge": ("usage: ak run merge ID",
                  "Retry delivery of a finished PASS; reverify if integration changes its commit.",
                  "ak run merge RUN_ID"),
    "run stop": ("usage: ak run stop ID [--keep]",
                 "Stop a run deliberately; --keep keeps its worktree and branch for a from: relaunch.",
                 "ak run stop RUN_ID"),
    "run clean": ("usage: ak run clean ID", "Remove a run's worktree.", "ak run clean RUN_ID"),
    "run gc": ("usage: ak run gc [--dry-run]",
               "Collect inactive temporary state and old merged checkouts; --dry-run only plans.",
               "ak run gc --dry-run"),
    "orch": ("""usage: ak orch [NAME] [--model MODEL] [--workers A,B] [--dry-run]
       ak orch list [--why] | ak orch why NAME
       ak orch stop NAME | ak orch rename [--auto] [OLD] NEW
       ak orch project [SEAT] CHECKOUT | ak orch rules CODE""",
             "Start or attach to a named orchestrator session; a new one opens only from a terminal.\n"
             "--dry-run prints the launch plan.",
             "ak orch parser-fix"),
    "orch rules": ("usage: ak orch rules CODE",
                   "Say this seat's conversation read the changed rulebook its prompt named,\n"
                   "with the code that prompt gave: its prompts stop naming it until it changes.",
                   "ak orch rules 3f2a9c81d0e4"),
    "orch list": ("usage: ak orch list [--why]",
                  "List orchestrator sessions and their selections;\n"
                  "--why adds what decided each seat's state, on what evidence, and since when.",
                  "ak orch list --why"),
    "orch why": ("usage: ak orch why NAME",
                 "Explain one seat's state: the authority, the rule or hook event,\n"
                 "the evidence line and when that state began.",
                 "ak orch why parser-fix"),
    "orch stop": ("usage: ak orch stop NAME", "Stop a session and remove its saved seat.",
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
               "Record a needs-you question or a job summary.\n"
               "--session and --dry-run apply to needs/done; --check checks without posting.",
               'ak notify done "Parser fixed" --session parser-fix --dry-run'),
    "notify needs": (f"usage: {NOTIFY_NEEDS}",
                     "Ask for a blocking decision: the question first, context after it.\n"
                     "--dry-run prints the payload without posting.",
                     'ak notify needs "Which branch?" --session parser-fix --dry-run'),
    "notify done": (f"usage: {NOTIFY_DONE}",
                    "Report the finished job; --dry-run prints the payload without posting.",
                    'ak notify done "Parser fixed" --dry-run'),
    "wait": ("usage: ak wait SESSION", "End this turn waiting on another session's work.",
             "ak wait fix-api"),
    "plan": ("usage: ak plan | ak plan add \"OUTCOME\" --check 'COMMAND' | "
             "ak plan add \"OUTCOME\" --eye | ak plan tick N | ak plan check N 'COMMAND'",
             "This session's plan: each line an outcome with the check that proves it.\n"
             "add runs the check on the project's default branch and refuses one that passes\n"
             "or does not finish; --eye is the owner's to judge, tick N marks it on their word.\n"
             "check N puts your own test in place of line N's check, such as a review\n"
             "follow-up's probe; it must fail on the commit the line names, where its check failed.\n"
             "Listing ticks each check line that now passes on its project's default branch;\n"
             "ak notify done runs every check again and waits for all.",
             "ak plan add \"each session sees its project\" --check 'python3 tests/test_x.py'"),
    "tell": ('usage: ak tell SESSION "TEXT"',
             "Queues it; ak types it into that session as soon as it can take a line, headed\n"
             "with who sent it; it never counts as the owner's words.",
             'ak tell fix-api "I am changing parser.py; leave it until my PR lands"'),
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
               "Show the slice the agents run in, the state of the tick, and any model\n"
               "set to an effort it does not take, which it names and never changes.\n"
               "Says `no slice` where the machine has no user systemd manager.",
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
}


# `ak --help` is one screen: the menu, then the commands an orchestrator uses, one line
# each, and under one dim `internal:` line the ones the toolkit runs for itself.
ORCHESTRATOR = ("run", "plan", "notify", "wait", "tell", "usage", "browser", "fetch")
INTERNAL = ("orch", "worker", "hand-in", "watch", "update", "macbridge", "attach", "doctor")

PURPOSES = {
    "run": "execute a task file to a merged PR",
    "plan": "show or write this session's checked plan",
    "orch": "open a seat",
    "worker": "run one headless model turn from a task or prompt file",
    "hand-in": "hand in review evidence or close a worker turn",
    "attach": "the menu",
    "usage": "show provider usage and worker pick order",
    "browser": "inspect the shared browser, sign in, register MCP tools, or install the stack",
    "update": "upgrade harnesses and verify with acceptance gates",
    "watch": "check PRs and stalled sessions",
    "doctor": "show the slice, the tick, and any model set to an effort it does not take",
    "notify": "record a needs-you question or a job summary",
    "wait": "end this turn waiting on another session's work",
    "tell": "send another session a message",
    "fetch": "copy requested Mac files to this host",
    "macbridge": "macOS only: forward requested files to the server over SSH",
}


def purpose(command):
    """The command's one-line purpose: the top table's for a top-level command,
    otherwise its description's first line."""
    if command in PURPOSES:
        return PURPOSES[command]
    return COMMANDS[command][1].splitlines()[0]


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
    usage, description, example = COMMANDS[command]
    # the one-line purpose first, then the usage and the rest of the
    # description as today: a description that opens by repeating the purpose
    # keeps only the purpose line, never the same sentence twice
    lines = description.splitlines()
    if lines and _same_sentence(lines[0], purpose(command)):
        description = "\n".join(lines[1:])
    body = f"{purpose(command)}\n\n{usage}"
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
