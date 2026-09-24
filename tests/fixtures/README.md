`claude-stream.jsonl` is the seven-event output of a real Claude Code 2.1.263 call,
captured on 2026-09-06 with `bash tests/smoke.sh --claude-stream <out-dir>`.
The model and effort come from `~/.agentkit/config.toml`. The prompt asks for `STREAM_READY`,
a Bash `pwd`, and `DONE`. The smoke helper confirmed that the runs viewer read
worker text before the process exited, and checked `final.md` and `session_id`
against the final result event.

Only local paths and request, tool, message, and session identifiers were redacted.
Event order, payloads, text, usage, and timing fields are otherwise preserved.

`claude-stall-pane.txt`, `codex-stall-pane.txt` and `muse-stall-pane.txt` are actual
100×30 `capture-pane -p` outputs from Claude Code 2.1.263, Codex 0.153.4 and Muse 1.0.3
on 2026-09-06. Refresh them with
`bash tests/smoke.sh --stall-panes <repo-local-output-dir> [claude codex muse]`.
The helper launches installed TUIs on its own `agentkit-test` socket, with isolated
homes and dummy keys. A loopback HTTP server returns a terminal Claude error and
quota errors for Codex and Muse; no provider is contacted. Only the Claude workspace
path was redacted. Blank space, completion timing, composer and footer are preserved.

The unit regressions also reproduce the earlier boxed Claude composer and Codex key
hints supplied in the review. Those examples are explicitly separate from these captures.
Smoke 34 replays the captures in test seats; its goal-stall variant substitutes the error
line while preserving Codex's actual footer.

The auth watchdog checks run offline with `bash tests/smoke.sh --auth-watch` and as part
of the full smoke suite. `claude-auth-pane.txt`, `codex-auth-pane.txt`, and
`unknown-stuck-pane.txt` derive from the captured stall panes above, replacing only the
error line. Claude's replacement is the owner's reported `Login expired · Please run
/login`; Codex's is an exact string inspected in the installed 0.153.4 executable:
`Your access token could not be refreshed. Please log out and sign in again.` The
unknown error is intentionally synthetic. These three are replay variants, not captures
of a real account expiring.

The unknown-error variant retains `The harness cannot proceed (unknown error)`.
`unknown-logout-pane.txt` substitutes the review's deliberately unfamiliar wording:
`Your session has expired · Run /login to continue`. Neither requires an `Error:` prefix.
Login/expiry cues or a blocked operation start the one-hour catch-all clock; plain
`Error:`/`Tests failed:` summaries, quoted examples, idle prompts and run-waiting messages
do not. Suspected auth also suppresses capacity nudges. Exited and legacy seats remain
excluded from the catch-all. New output releases its alert latch, including when the
new output is a capacity error that needs the existing resume path.

`claude-auth-401-pane.txt` and `codex-auth-401-pane.txt` are actual installed Claude Code
2.1.263 and Codex 0.153.4 panes captured on 2026-09-11 using dummy keys and a loopback
HTTP 401 response. Refresh via `bash tests/smoke.sh --stall-panes <repo-local-dir>
--auth claude codex`. Only the workspace path and loopback port were normalised.
The wrapper text (`Please run /login · API Error: 401 Invalid API key` and
`unexpected status 401 Unauthorized: Invalid API key, url: …`) is the harness's own.
Claude 2.1.263's installed executable constructs its default auth error by prepending
`Please run /login · API Error:` to the status and arbitrary server details. The auth
checks replay this capture with both 401 and 403 and several different server messages,
including OAuth expiry/revocation and JSON. The latest output line's login instruction
must win regardless of those details; newer output or a quoted example must not match.
These checks replace the earlier synthetic JSON line that omitted Claude's login wrapper.

`muse-auth-pane.txt` is Muse 1.1.1's actual logged-out chooser, captured on the private
test socket with an isolated empty home after cancelling its browser login prompt;
no login was completed. The installed `muse-bin-1.1.1-R2514.1` executable also contains
`not logged in: run /login to add an API key`, `starting logged out (run \`muse login\`)`,
and `still unauthorized after a token refresh; run \`muse login\` again`. The recogniser
uses these exact strings, not a generic `401`, `unauthorized`, or an MCP login status.
Codex's other refresh-failure sentence and Claude's expiry message were also verified
in their installed executables. No harness entry depends on an unverified guessed string.

`auth-expiry-variants.json` records the additional logout messages reported in review
and confirmed by inspecting these same installed binaries. It includes Claude's revoked
and missing login messages and external-key failure, Codex's expired/revoked/already-used
refresh tokens and automatic refresh failure, and Muse's missing saved login/key refresh.
The smoke checks substitute each message into the captured panes, wrap it, and verify an
immediate login alert, deduplication after a watcher restart, and no resume. Muse's two
additional strings are verified literals; their exact mid-session rendering remains
uncaptured. No account login or model call is needed to replay these checks.

`grokbuild`'s `*-pane.txt` come from a private tmux socket's `capture-pane`, run against
Grok Build 1.0.40: `grok-prompt-pane.txt` a resumed session sitting at its prompt,
`grok-working-pane.txt` a turn mid-stream (the `⠼ Responding…` line over the composer, the
footer turned to `Ctrl+c:cancel`), `grok-draft-pane.txt` and `grok-suggestion-pane.txt`
`-e` captures of a typed draft and the empty box. The `dialog`, `stall` and `auth` panes
are replay variants, not captures: a real composer tail with the wording being asserted
above it. The trust dialog's words are the executable's own strings -- no fresh folder on
this host was still untrusted enough to paint it, so its layout is assumed and its rule
carries no `newest` anchor (the composer stays painted under every grok dialog). The stall
and auth words were read out of the same executable and match what the CLI prints.

`grok-events.jsonl` is a real headless turn (`grok -p`, one line in, `ok` out), kept whole
so `history.event_tokens` reads the harness's own `usage` objects. `grok-hook-*.json` are
real hook payloads from a logging hook that was removed again (home directory normalised):
the `UserPromptSubmit`/`Stop` shapes from a headless turn, the `idle_prompt` Notification
from a TUI left sitting a minute. `grok-auth-valid.json` and `grok-auth-expired.json` are
fake `~/.grok/auth.json` files in the real shape, timestamps fixed far out and far back.
`grok-settings-none.json` is the settings cache shaped as the CLI writes it -- tier display
and no meter entries -- and `grok-settings-meters.json` the same cache with the
`subscription_usage` entries the usage verb would answer, which no real cache has carried
yet. `grok-billing-weekly.json` is the wire body of `GET /v1/billing?format=credits`
captured 2026-09-22 (the Usage limit tab's weekly window, no token in it).
`grok-billing-credits.json` is those fields in the protobuf shape the parser also accepts,
and `grok-billing-nometer.json` is `/v1/billing` without `format=credits`: spend, and no
percent.

Re-auth feasibility (inspection only; not implemented): Claude's executable supports
stored OAuth refresh tokens, `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, and
`ANTHROPIC_API_KEY`; `claude auth login --help` exposes browser/SSO flows, not a
non-interactive replacement for a revoked subscription login. Codex's `login --help`
supports `--with-api-key` and `--with-access-token`, both reading stdin; its executable
already refreshes stored OAuth tokens and reports terminal refresh failure. Muse's
`login --help` says browser approval is required and `META_API_KEY` takes priority;
its executable contains refresh-token handling and the failure message above. Valid
stored refresh tokens or supplied keys can support unattended operation, but expired
or revoked refresh credentials still need fresh credentials or owner approval. These
checks neither read real credential files nor attempt automatic re-authentication.

`codex-hooks-review-pane.txt` is the Codex 0.153.4 startup hook review screen captured on
2026-09-11 in an isolated test seat with a dummy API key and a harmless `true` hook. Only
outer blank lines were removed. Selecting `3`, then Enter reached the normal TUI without
trusting the hook or making a model request; smoke 6d uses that same choice.

`v4z-40.txt` and `v4z-100.txt` come from the real renderer with fixed fake state in
`tests/test_v4z.py`: ATOLL, agentkit, newsletter-tool and scratch; running, asking,
waiting, recovery and PASS states. Refresh with `python3 tests/test_v4z.py --fixtures`.
Run the named checks with `bash tests/smoke.sh --projects`. The 100-column screen shows
run details and blue usage bars; at 40 columns run details and usage fold to preserve
project headers and seat rows. The suite also checks collapsed project pages, stable
numbers, project selection/inference, colour and locale fallbacks, and an isolated tmux bar.
The older v4n/v4r exact snapshots are replaced; their width and usage regression tests remain.
Since v5k nothing in these snapshots is read from git: the suite patches `menu.installed`,
the checkout's short commit and date, to a fixed `abc1234 · 15 Sep`, and points `config.REPO`
at a directory with no history, so the same screens are drawn in a fresh clone, in a tarball
and in a checkout with commits.  The pinned value reaches no fixture -- the header is
`agentkit` and the clock, pinned to `14:02`, over one dim rule -- and usage rows read
`NN% left`.
Since v5g the 100-column screen carries each seat's tally of runs after its state
(`1 running · 0 merged`, `0 running · 1 needs a look`, `no runs yet`); at 40 columns the tally
is the first column dropped, so `v4z-40.txt` is unchanged.

`v5g-100.txt` and `v5g-40.txt` come from the same renderer with the fixed state in
`tests/test_v5g.py`: herdr with a run going and one merged, atoll-fix with three merges this
week (a fourth is eight days old, an interruption was acknowledged), atoll-proxy with a failure
nobody acknowledged beside two merges, and scribe with no runs. The clock is pinned to
1 800 000 000 and the title's version lookup to `3de8bef · 14 Sep`, so nothing in them moves
with the checkout. Refresh with `python3 tests/test_v5g.py --fixtures`.

## Seat-state captures (v4y)

`claude-prompt-pane.txt`, `claude-working-pane.txt`, `claude-dialog-pane.txt` and the same three
for `codex` and `muse` are actual 100×30 `capture-pane -p` outputs from **Claude Code 2.1.263**,
**Codex 0.153.4** and **Muse Code 1.2.1**, captured on 2026-09-13. Refresh them with
`bash tests/smoke.sh --stall-panes <repo-local-output-dir> --state <prompt|working|dialog> [harness]`.
The helper is the one that captures the stall panes: installed TUIs on its own `agentkit-test`
socket, isolated homes, dummy keys, and a loopback HTTP server. No provider is contacted.
Only the workspace path was redacted, to `/…/fixture-workspace`.

* `-prompt-` is the composer with nothing running, captured by launching the TUI with no first
  message. Offline there is no model to complete a turn with, so this is a fresh prompt rather
  than the prompt after an answer; the `*-stall-pane.txt` captures are the same screen after a
  turn that ended in an error, and the unit checks replay both through the at-the-prompt rule.
* `-working-` is a turn still in flight: the loopback server holds the request open while the
  pane is captured. Claude, Codex and Muse say `esc to interrupt` there, which is what
  `[[rule]] id = "working.interrupt"` matches in each adapter manifest; OpenCode 2.0.13 says
  `esc interrupt`, with no `to`, and its rule matches that instead.
* `-dialog-` is the harness's own approval screen, the only kind reachable with no provider
  behind it: Claude's and Codex's workspace-trust prompts, and Muse's logged-out chooser.
  `codex-hooks-review-pane.txt` is a second Codex dialog and is replayed through the same rule.

**Not captured.** Claude Code's permission prompt needs a tool call, which needs a model, so
there is no fixture for it and `adapters/claude.toml` declares no screen rule for its shape.
Its authority is the `Notification` hook instead. Muse has no approval dialog of its own to
reach offline; its picker is the only screen it stops on and waits.

`opencode-prompt-pane.txt`, `opencode-working-pane.txt`, `opencode-dialog-pane.txt` and
`opencode-auth-pane.txt` are actual 100×30 `capture-pane -p` outputs from **OpenCode 2.0.13**,
captured on 2026-09-22 the way the v4y panes were, except the working pane: installed TUI on
a private test socket, isolated homes and (for the auth pane) a dummy key that the real MiMo
endpoint refused with `Invalid API Key`. Only the workspace path was redacted, to
`/…/fixture-workspace`. The working pane needed a model -- OpenCode renders `esc interrupt`
only while tokens stream -- so it holds a real turn mid-answer, cut at the pane. The dialog
is the harness's own permission prompt (`Allow once`, `Always allow`, `Reject`, `enter
confirm`) from a seat opened without `--auto`; seats opened with it, as agentkit's are, are
never asked. The auth pane is a bad-key turn's `Error: Invalid API Key` above a fresh
composer. This harness's stall and refusal words come from these panes, the headless event
shapes beside them (`{"type":"error","error":{"type":"provider.*","message":...,"status":...}}`,
observed for a bad key, a missing key, an unknown model and a loopback 429), and exact
strings inspected in the installed executable (`provider.rate-limit`, `provider.quota`).
MiMo's own 429 text was never observed, and no entry depends on a guessed string. There are
no draft or suggestion fixtures for this harness: its composer is a `┃` box, not a `❯›⟩`
mark, and its placeholder is grey (`38;2;128;128;128`) rather than faint, so the generic
draft machinery cannot read it and `adapters/opencode.toml` declares no rule for either.
`opencode-stall-pane.txt` is a replay variant of the auth pane, replacing only the error
line the way the v4y auth panes were made: `Error: 429 Too Many Requests`, OpenCode's own
`Error: ` rendering with the condition's own status number, since MiMo's exact 429 text was
never observed. The finished-turn footer under the error (`Build · mimo-v2.6-pro · 166ms`)
is the capture's own; its shape -- `<agent> · <model> · <duration>` with optional `· <tps>
tok/s` and `· interrupted` tails -- is confirmed in the installed executable's
assistant-footer renderer.

`antigravity-prompt-pane.txt`, `antigravity-working-pane.txt`, `antigravity-dialog-pane.txt` and
`antigravity-signin-pane.txt` are actual 100×30 `capture-pane -p` outputs from **agy 1.2.9**
(Google's Antigravity CLI), captured on 2026-09-23 on a private tmux socket. The prompt and
working panes are a signed-in seat opened the way `adapters/antigravity.sh interactive` opens
one -- `--add-dir` and `--agent agentkit` over a probe agent whose prompt asked for the words
around the answer -- at its prompt after a turn and mid-turn (`⣯  Generating...` over `esc to
cancel`); the dialog is the workspace trust question a fresh folder opens on, and the sign-in
pane is the chooser a HOME with no login opens on. The workspace path became
`/…/fixture-workspace` and the account's address `owner@example.com`. `antigravity-stall-pane.txt`
is a replay variant of a real failed turn from the same seat: agy drew it as `⚠ <message>` over
`Error ID: <id>`, and only the message was replaced, by the executable's own `You have exhausted
your quota on this model.`, with the warning block drawn under it dropped. The other stall words
are the executable's own strings, and `RESOURCE_EXHAUSTED` and `UNAVAILABLE` the canonical
statuses its stderr names; a real 503 (`Eligibility check failed ... UNAVAILABLE (code 503)`) was
seen on a live turn, and a status number is matched only in that `(code N)` framing, the
executable's own `%s (code %d): %s`. `antigravity-draft-pane.txt` and
`antigravity-chooser-pane.txt` are the same kind of seat, launched in a folder already trusted,
with a line typed and never sent -- the footer loses its left-hand key hint -- and with the
slash-command chooser a typed `/` opens; nothing was sent to a model for either.
`antigravity-events.jsonl` is a real headless `--output-format stream-json`
turn that ran one command and answered `done` (working directory normalised), and
`antigravity-error-events.jsonl` the stream of a turn refused for an unknown model. The auth
signatures are the stderr lines a headless turn printed with no login, under a temporary HOME.

`antigravity-models.txt`, `opencode-models.txt` and `grok-models.txt` are the unedited stdout
of `agy models` (agy 1.2.9, signed in), `opencode models` (OpenCode 2.0.14, against its
background service, with the `mimo` provider configured) and `grok models` (grok 1.0.40, logged
in with grok.com), captured on 2026-09-24. agy prints one tab-separated id and label per model
and effort; OpenCode one `provider/model` id a line; grok a greeting, its default, and one
`* id` or `- id` line per model. `codex-models.json` is the stdout of `codex debug models`
(codex 0.153.4, a ChatGPT login, the same day) cut to each model's `slug`, `display_name`,
`visibility` and `supported_reasoning_levels`, the fields the adapter reads.
tests/test_catalog.py replays them through stub binaries.

`antigravity-usage-pane.txt` is agy 1.2.9's `/usage` panel, captured 2026-09-24 as a 100×30
`capture-pane -p` on a private tmux socket (`tmux -L <private> new-session -x 100 -y 30`), in a
folder agy already trusted: `agy` opened, `/usage` typed and sent, the pane captured, the seat
killed. `/usage` is agy's own panel and asks no model. Only the account's address was replaced,
by `owner@example.com`. `antigravity-quota-summary.json` is the wire body of the call that panel
is drawn from, `POST https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary`
(the host and method agy's own log names), taken minutes earlier with agy's login and the
`project` agy's `loadCodeAssist` answer names, the request `antigravity.sh usage` makes; it
carries neither, and is unedited. Its Gemini window, 0.917436 left, is the panel's 91.74%.

## Seat-state captures (v5n)

`claude-draft-pane.txt`, `codex-draft-pane.txt`, `muse-draft-pane.txt` and the matching
`*-suggestion-pane.txt` are actual 100×30 `capture-pane -p -e` outputs from **Claude Code 2.1.263**,
**Codex 0.153.4** and **Muse Code 1.3.0**, captured on 2026-09-16 on `tmux -L agentkit-test`
the way the v4y panes were: installed TUIs on the test socket, isolated homes, dummy keys,
and (for Muse's model catalogue) a loopback server; no provider was contacted. Only the
workspace path was redacted, to `/…/fixture-workspace`. Blank space, composer and footer are
preserved, and every file holds SGR attributes (`\x1b[`) so dim tells from typed.

* `-draft-` is a typed, unsent line: `Fix the login redirect` typed into the composer and
  captured before Enter. The text is bright (no faint span), so `prompt.draft` fires and the
  seat reads `draft unsent` with the draft as its row text.
* `-suggestion-` is an empty box: Codex's dim `Ask Codex to do anything` placeholder
  (`\x1b[2m`), Muse's empty box (Muse has no suggestion feature, so its suggestion fixture is
  its placeholder), Grok's empty box (likewise), and Claude's empty box with attributes —
  the real `❯` plus its inverted cursor block, and nothing else. Claude's dim ghost (a suggestion captured on 15 Sep,
  `❯ you write it`, drawn dim inside the empty box; typing replaces it, deleting brings it
  back) is painted by the model-pushed `inlineGhostText` path: a fresh prompt, a failed turn,
  an interrupted turn, history recall, `@`/`/` menus, permission-mode cycling, a resume and
  the queued-message composer were all captured live on the test socket and none of them
  paints SGR 2 in the composer, so no offline capture can hold one. `tests/test_v5n.py`
  replays both captured texts (`you write it` and
  `Also fix the login page non-200 thing you mentioned`) in the bundle's verified ghost
  shape — the inverted first character with only the remainder faint — through the same
  `prompt.suggestion` rule the real Codex placeholder exercises. A dim-only composer is
  empty: `prompt.suggestion` (and the plain `prompt.composer`) reads `idle`.

## Hook events, verified against the installed harnesses

Read out of the installed executables on 2026-09-13, not assumed:

* **Claude Code 2.1.263** emits `UserPromptSubmit`, `Stop` and `Notification`. The Notification
  payload is `{hook_event_name, message, title, notification_type}`; the types it constructs are
  `permission_prompt` (from a six-second timer after a prompt goes up, cancelled if it is
  answered first), `worker_permission_prompt`, `agent_needs_input`, `agent_completed`,
  `idle_prompt` ("Claude is waiting for your input"), `auth_success`, `push_notification`,
  `computer_use_exit` and the `elicitation_*` pair. **There is no counterpart when a prompt is
  answered**, which is why a hook fact gives way to a screen rule that positively names a
  different state; `tests/smoke.sh` check 42(b2) holds that behaviour.
* **Codex 0.153.4** emits `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `Stop`, `Interrupt`,
  `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`, `PermissionRequest`, `PreCompact`
  and `PostCompact`. `PermissionRequest` carries `tool_name`, which the hook records as the
  event's kind. `Interrupt` is what ends a turn the user escapes out of.
* **Muse Code 1.2.1** has no lifecycle hooks; `adapters/muse.sh hooks` says so and writes
  nothing. Muse 1.2.1 also draws `❯` where 1.0.3 drew `⟩`; the shared footer already reads both.
* **OpenCode 2.0.13** takes its hooks as a v2 plugin (`export default {id, setup}`) fed by the
  server's event stream. agentkit's ships as `hooks/opencode-seat` and is named per launch in
  `OPENCODE_CONFIG_CONTENT`, so nothing is written into the user's own config. It translates
  three of the stream's own events to the one protocol `hooks/seat-state.sh` speaks:
  `session.inbox.enqueued` (a user message) arrives as `UserPromptSubmit` with its text,
  `session.execution.{succeeded,failed,interrupted}` as `Stop` with the session id and the
  last step's token total for the idle-compact stamp, and `permission.asked` as
  `PermissionRequest` with the action as its kind. The mapping was verified end to end: a
  headless turn with the plugin loaded wrote a `UserPromptSubmit` fact with the prompt's text
  and a `Stop` fact when the answer ended.

## v5o menu at rest (`v5o-40.txt`, `v5o-100.txt`, `v5o-170.txt`)

One fixed fake state over three widths, rendered with `menu.draw` under pinned
`14:02` and `COLUMNS`/`LINES` (`ak --dry-run </dev/null` draws the same). It holds:
a seat with a job (3 of 7 tasks done, two runs on opus and astra, the running
task's title as its sentence), a seat with one run and no job, an idle seat, a seat
that needs the owner with a long question, a project with no seat and one unfinished
run, and a merged run that must not appear. `tests/test_v5o.py` checks all three
byte for byte; the reviewer renders the same three and reads them as the owner would.
Refresh with `python3 tests/test_v5o.py --fixtures`.

## v5ai usage bars are one column (`v5ai-40.txt`, `v5ai-100.txt`)

One fixed fake usage record over two widths, rendered with `menu.usage_lines`
under a pinned clock: Claude carries `(Fable 98%)`, ChatGPT is spent with
`back 21 Sep` and Muse carries `22m old`. At 40 columns every bar is the one
width the row with the least room can afford; at 100 columns every bar is 12
cells, as before. `tests/test_v5ai.py` checks both byte for byte.
Refresh with `python3 tests/test_v5ai.py --fixtures`.

## Refused-run terminal records (v5i)

A refused run's terminal event-log record is `turn.failed` (Codex), `result` (Claude) or
`payload.kind == "run_terminal"` (Muse), each named under `[stall] terminal` in its manifest.
OpenCode names none: a trivial turn ends on `text`, a tool turn on `step_finish` and a refused
one on `error`, and the error record declares itself a failure (`"error"` key, `"error"`
type), so only failure records are read from its log. The adapter appends the session's own
token totals as a `result` record for `history.event_tokens`; that line is agentkit's, not
the harness's, and no stall matching reads it.

## A Stop on background work (Claude Code 2.1.280)

`claude-stop-background.json` is a real Stop hook payload from **Claude Code 2.1.280**, captured
on 2026-09-23 by a logging hook beside `hooks/seat-state.sh` and `hooks/orchestrator-stop.sh` in
a headless haiku turn that started a background Bash `sleep` and a background subagent, then
ended its turn. `background_tasks` is the harness's own list of work still in flight (its
executable describes it as "in-flight background work ... empty array when nothing is in
flight"; 2.1.263 builds it the same way). Only the session and prompt ids, the transcript path
and the working directory were redacted. The same capture showed each task notification
starting its turn with `UserPromptSubmit`. The same day an interactive 2.1.280 seat on a private
tmux socket showed the other half: a minute into a wait on a background `sleep`, its idle
notifier sent the `idle_prompt` Notification all the same, which is why `hooks/seat-state.sh`
leaves a `background` Stop standing under one.
