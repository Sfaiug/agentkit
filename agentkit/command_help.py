"""Public command help, safe to print before importing operational command modules."""

WORKER_USAGE = ("usage: ak worker MODEL TASK [--workspace DIR] [--out DIR] [--session ID]\n"
                "       [--role executor|reviewer|fixer|reviewer-pr|executor-scratch|"
                "fixer-scratch|reviewer-scratch]")
NOTIFY_NEEDS = 'ak notify needs "QUESTION" [--session NAME] [--dry-run]'
NOTIFY_DONE = ('ak notify done "SUMMARY" [--pr URL] '
               '[--session NAME] [--dry-run]')
NOTIFY_USAGE = (f"usage: {NOTIFY_NEEDS}\n       {NOTIFY_DONE}\n"
                "       ak notify --check")

# Each entry is (usage, description, example). Model selections remain in config.toml;
# MODEL in usage/examples stands for one of that file's keys.
COMMANDS = {
    "usage": ("usage: ak usage [--json]", "Show provider usage and worker pick order.",
              "ak usage --json"),
    "worker": (WORKER_USAGE, "Run one headless model turn from a task or prompt file.",
               "ak worker MODEL task.md --role reviewer"),
    "run": ("""usage: ak run TASK [TASK ...] [--rounds N] [--exec MODEL] [--review MODEL]
              [--anyway] [--first] [--no-worktree] [--no-merge] [--bg] [--parallel N]
       ak run --review-pr URL [--review MODEL] [--first] [--no-merge] [--bg]
       ak run status [ID] [--history] [--why] [--plain] [--json]
       ak run resume ID [--rounds N] [--bg]
       ak run stop ID [--keep]
       ak run merge ID | ak run clean ID | ak run gc [--dry-run]""",
            """Execute, verify, review, push, open a PR and merge.
--rounds sets the round limit, at most 3 (default: task rounds or 3).
--anyway starts even when a run in the same repository looks already under way;
a task bigger than one behaviour or over 3 rounds is refused regardless.
--no-worktree uses the repo's current branch; --no-merge keeps work local.
--bg detaches and prints a launch receipt, run ID and result path.
--first admits the run ahead of every queued run without it, skipping the count cap and the load gate, and takes its repository's next gate turn first.
Several task files run as one job; after: names a dependency, --parallel caps it.
max_runs caps the count when positive; 0 leaves host memory and load as the gates
(config.toml or AK_MAX_RUNS).
--review-pr reviews someone else's GitHub PR, without an executor.
Task fields: repo, base, target, from, merge (squash|merge|rebase), rounds, after.""",
            "ak run task.md --bg"),
    "run status": ("usage: ak run status [ID] [--history] [--why] [--plain] [--json]",
                   "Show current work and result paths; --history includes older runs.",
                   "ak run status --history --json"),
    "run resume": ("usage: ak run resume ID [--rounds N] [--bg]",
                   "Resume interrupted or exhausted work; --rounds raises the round limit, at most 3.",
                   "ak run resume RUN_ID --rounds 3 --bg"),
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
       ak orch stop NAME | ak orch rename [OLD] NEW""",
             "Start or attach to a named orchestrator session; --dry-run prints the launch plan.",
             "ak orch parser-fix"),
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
    "orch rename": ("usage: ak orch rename [OLD] NEW",
                    "Rename a session; omit OLD to rename the session this runs in.",
                    "ak orch rename parser-fix parser-review"),
    "notify": (NOTIFY_USAGE,
               "Record a needs-you question or a job summary.\n"
               "--session and --dry-run apply to needs/done; --check checks without posting.",
               'ak notify done "Parser fixed" --session parser-fix --dry-run'),
    "notify needs": (f"usage: {NOTIFY_NEEDS}",
                     "Ask for a blocking decision; --dry-run prints the payload without posting.",
                     'ak notify needs "Which branch?" --session parser-fix --dry-run'),
    "notify done": (f"usage: {NOTIFY_DONE}",
                    "Report the finished job; --dry-run prints the payload without posting.",
                    'ak notify done "Parser fixed" --dry-run'),
    "wait": ("usage: ak wait SESSION", "End this turn waiting on another session's work.",
             "ak wait fix-api"),
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
                             "Register browser and desktop MCP servers with Claude and Codex.",
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
ORCHESTRATOR = ("run", "notify", "wait", "usage", "browser", "fetch")
INTERNAL = ("orch", "worker", "watch", "update", "macbridge", "attach", "doctor")

PURPOSES = {
    "run": "execute a task file to a merged PR",
    "orch": "open a seat",
    "worker": "run one headless model turn from a task or prompt file",
    "attach": "the menu",
    "usage": "show provider usage and worker pick order",
    "browser": "inspect the shared browser, sign in, register MCP tools, or install the stack",
    "update": "upgrade harnesses and verify with acceptance gates",
    "watch": "check PRs and stalled sessions",
    "doctor": "show the slice, the tick, and any model set to an effort it does not take",
    "notify": "record a needs-you question or a job summary",
    "wait": "end this turn waiting on another session's work",
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
