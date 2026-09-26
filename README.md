# agentkit

You talk. It ships.

One command installs it. One word opens it. You tell one orchestrator what you want, and agentkit works until the change is merged or it truly needs you. Then it tells you, once.

## Install

```bash
git clone https://github.com/Sfaiug/agentkit ~/agentkit && ~/agentkit/install.sh
```

On a terminal, and only for what is missing, it asks: which harness to install when there is none (one, or `all`; one is enough, and a run on a machine that has one keeps what it has and adds none), each harness's login, `gh auth login`, `sudo tailscale up`, the Claude worker token `claude setup-token` prints, and a Discord webhook URL and user id (Enter skips those three). sudo asks for its password where packages are missing. Everything else has a default that works.

## Use

Type `ak`. One screen: your sessions, what each is doing, and one line at the top: `nothing needs you` or `2 need you`. Six keys:

```
1 2 3   open that session
n       start a session
x       stop a session, or close a done one
c       change the config
i       show info
q       leave
```

On a terminal a key acts the moment you press it, no Enter. One session is highlighted: ↑↓ (or `k` `j`, or the wheel) move it and Enter opens it. A click on a session opens it, and a click on the key line does what that key does. Two digits within half a second are one number.

`x` is the highlighted session's. When a session is done, press `x` on it and it is closed at once: its runs, checkouts, conversation and files go with it, and the key line says `x close` while it is highlighted. Any other session asks first, under its row: `Stop <name> and everything it runs?`, with `Keep` picked until you move to `Stop`; Esc keeps it. `i` is one screen: the three states, the keys, the worker token's date and the build. Esc goes back.

`c` is every model once, under its company: `●` marks the orchestrator a new session takes, `■` its workers, and `‹ xhigh ›` is the model's effort. ↑↓ move between models and ←→ between those columns, the effort's too; Enter, space or a click flips a mark, Enter or space on an effort steps it up through that model's own efforts and from the highest back to the lowest, and a click on `‹` or `›` steps it down or up. Each change is saved at once, and the last worker stays. ← from the marks reaches a model's label, and Enter there opens its own screen: its model id picked from its harness's catalog (the effort stays if the new model takes it, else moves to the nearest it does), its effort, `Reviews its own company's work` (yes or no), and `Remove`, which asks `Keep` or `Remove` and is refused for the last model. Esc goes back to its row. Under the models, `+ add a model` is three lists in one screen: a harness of a company the config has, then a model its catalog offers (one already configured is marked, and can be added at another effort), then an effort that model takes; Enter on the effort adds it, named from its label (`sonnet`, `sonnet-2`), and Esc steps back one list. `Providers` lists your providers in their colours; ←→ choose `+ add` or `− remove`. `+ add` offers the ones agentkit ships that you have not added, installs the one you pick if its harness is missing, logs it in on the terminal, and adds it as it ships with its catalog's first model. `− remove` asks `Remove <provider> and its models?`, `Keep` picked, and takes its models and its usage row with it; the last provider stays. Enter runs `Discord` (connected or not; its two secrets are the only typing left) and `Update` (the build, then `up to date` or the newer commit). Esc goes back.

A session is one of three things, and nothing else:

```
! needs you   it asked you something, or it cannot go on without you
● working     a run of its own is going, or a turn is, or a session it waits on works
✓ done        it said so, and the row carries its summary
```

The word moves when the session's harness starts or ends a turn or asks something: at once on the session's own tmux bar, which names its orchestrator and workers (`ak-verification · opus → opus astra · ● working · tasks ████░░░░ 4/8`), and within two seconds on an open menu.

Press `n`, then Enter. `n` is one screen with your defaults already chosen:

```
Orchestrator
  ○ Fable 5.1    claude · xhigh
› ● Opus 5.5     claude · xhigh
  ○ Astra        codex · xhigh

Workers
  □ Fable 5.1    claude · xhigh
  ■ Opus 5.5     claude · xhigh
  ■ Astra        codex · xhigh
```

Every model is in both lists. ↑↓ move, space or a click chooses, Enter starts from anywhere, Esc goes back; one worker always stays chosen. A model whose provider is spent reads dim with `spent · resets Fri 14:00` and is never chosen for you. The session is named for its orchestrator (`opus`, then `opus-2`); `r` in its `Ctrl-b m` menu renames it. That is all. No project: the session files itself under the project most of its runs belong to.

Say what you want. The orchestrator asks until the goal is clear and checkable, then goes. Close the terminal.

## While you are away

Agentkit does not stop until the work is merged, or until it truly needs you. Truly needs you means exactly two things: a question only you can answer, or a failure it has tried every way around. Everything else it handles itself: a provider running dry or down for hours, a crash, a reboot, main moving underneath (its own runs of one repository land one at a time), its own upgrade (a run takes the new code at its next round, saying `picked up agentkit <old>..<new>`), a reviewer that hesitates, a test budget that was too small, a stuck session.

Every change is written by one model, checked by commands the orchestrator agreed with you, and reviewed by a different model before it merges, from a different company where your workers allow it. No model marks its own work. A task is one behaviour and three rounds: a bigger task or more rounds is refused before it starts, `--anyway` or not, and work its reviewer still fails after the third goes back to the orchestrator with the findings, to split or re-scope.

## New features in live projects

A hobby project ships straight to live. The first time a new feature comes up in a project, the orchestrator asks once whether it has real users, and the answer goes into the front matter of its `AGENTS.md`: `users: none` or `users: real`. In a `users: real` project a new feature merges round by round but stays hidden behind the project's own switch, on only for you until you turn it on for everyone; the reviewer fails a round that shows it to anyone else. A switch on for everyone for more than 14 days comes out of the code. The project names the one command that lists and flips its switches in the same front matter, `features: <command>`, which answers `<command> list` and `<command> set <id> you|everyone on|off`. The `ak` menu then lists the project whether or not a session sits in it, as `ACME · 2 hidden features`, and Enter on that heading opens its switches, `you` and `everyone` for each feature, flipped with the arrow keys and Enter; the project's own owner page flips the same ones.

## Hearing back

One Discord card when a session needs you. One when the whole job is done. Two words and the session name, nothing else. Never for a session you closed yourself, never twice for the same done, and never after an upgrade for anything that stood before it. Open the host, press the session's number, read, answer. A tmux session with no agent in it, such as a watcher loop, is not a session and never sends one; the card of a session that is gone is closed on the next tick, and the card of one you stop or close reads `Answered` at once.

## Never needed

Choosing a project. Editing config. Merging. Cleaning up: a stopped session leaves nothing of itself behind, and a daily pass takes every checkout, seat file and harness trust entry nothing uses any more. Restarting anything. Reading a manual. The whole help fits on one screen.

## Plugins

A model is a few lines in `~/.agentkit/config.toml`, or press `c` and add one. Every model can orchestrate and work; `c` also sets the defaults Enter takes. A harness is two files under `adapters/`, and says which models it runs and the efforts each takes (`adapters/<h>.sh models`); `ak doctor` names a model set to an effort it does not take. Claude Code, Codex, Muse, Grok Build, OpenCode and Google's Antigravity CLI (`gemini`) come wired in. One provider is enough to start: a harness that is not installed or not logged in is never picked, two models of the one provider left execute and review, and `ak run` refuses in one sentence when the workers leave no allowed pair; workers from two providers allow review by a different company.

How it all works, the installer, the acceptance gates and troubleshooting: [the guide](docs/guide.md).
