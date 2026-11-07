package tmux

import (
	"os"
	"strings"
	"testing"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

// wayBack is what a seat's pane left dead says, where tmux would say `Pane is dead` (orch.WAY_BACK).
const wayBack = "The harness ended. To open it again: Ctrl-b m, then this seat's number."

// Hooks are the server's options that run ak (orch.hook_options): what brings back a seat whose
// harness ended without ak ending it, and what puts the seat a client is in first (`front`).
//
// tmux runs pane-died when a pane's program exits or is killed under remain-on-exit, and never for
// respawn-pane -k or kill-session, the ways ak ends one: so the owner's /exit, a crash and a kill
// from outside run `ak orch ended`, and no relaunch or stop of ak's does.  Server-wide, as tmux 3.5
// holds the hook per window, not per seat.  ak is named by its path: the server's PATH may hold
// none.  run-shell draws a job's output, and its failure, over the pane, so the tick's log takes
// all of it and the job always succeeds.  A pane left dead says how to open it again; a tmux before
// 3.3 has no option for that, and setting these with -q keeps it quiet.  A test's own binary is
// no ak: named in a hook, it would run its whole test again at each pane's end, whose panes end in
// turn, so a test's server gets none.
func Hooks() ([][2]string, error) {
	program, err := os.Executable()
	if err != nil || testing.Testing() {
		return nil, err
	}
	ak := unformatted(commandhelp.ShellJoin([]string{program, "orch"}))
	log := unformatted(commandhelp.ShellJoin([]string{config.TickLog()}))
	job := func(verb string) string {
		return "run-shell -b " + Word(ak+" "+verb+" >>"+log+" 2>&1; true")
	}
	front := job("front")
	return [][2]string{{"pane-died", job("ended #{q:session_name} #{pane_dead_time}")},
		{"remain-on-exit-format", wayBack},
		{"client-attached", front}, {"client-detached", front}, {"client-session-changed", front}}, nil
}

// unformatted is literal text for a tmux option, its `#`, which starts a format, doubled.
func unformatted(literal string) string { return strings.ReplaceAll(literal, "#", "##") }
