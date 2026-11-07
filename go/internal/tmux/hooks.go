package tmux

import (
	"os"
	"os/exec"
	"path/filepath"
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
// 3.3 has no option for that, and setting these with -q keeps it quiet.  An end this program
// hands over, exit 3, is Python's ak's to take up where there is one.  A test's own binary is no
// ak: named in a hook, it would run its whole test again at each pane's end, whose panes end in
// turn, so a test's server gets none.
func Hooks() ([][2]string, error) {
	program, err := os.Executable()
	if err != nil || testing.Testing() {
		return nil, err
	}
	log := unformatted(commandhelp.ShellJoin([]string{config.TickLog()}))
	run := func(ak []string, verb string) string {
		return unformatted(commandhelp.ShellJoin(append(ak, "orch"))) + " " + verb + " >>" + log + " 2>&1"
	}
	job := func(line string) string { return "run-shell -b " + Word(line+"; true") }
	ended := run([]string{program}, "ended #{q:session_name} #{pane_dead_time}")
	if python := python(program); python != nil {
		ended += "; [ $? != 3 ] || " + run(python, "ended #{q:session_name} #{pane_dead_time}")
	}
	front := job(run([]string{program}, "front"))
	return [][2]string{{"pane-died", job(ended)}, {"remain-on-exit-format", wayBack},
		{"client-attached", front}, {"client-detached", front}, {"client-session-changed", front}}, nil
}

// python is Python's ak: its bin/ak under the python3 the PATH finds, as its `#!/usr/bin/env
// python3` runs it.  None where the program is that bin/ak, or finds no bin/ak or no python3.
func python(program string) []string {
	python3, err := exec.LookPath("python3")
	if err == nil {
		python3, err = filepath.Abs(python3)
	}
	bin := filepath.Join(config.Repo(), "bin", "ak")
	ours, unseen := os.Stat(program)
	theirs, missing := os.Stat(bin)
	if err != nil || unseen != nil || missing != nil || os.SameFile(ours, theirs) {
		return nil
	}
	return []string{python3, bin}
}

// unformatted is literal text for a tmux option, its `#`, which starts a format, doubled.
func unformatted(literal string) string { return strings.ReplaceAll(literal, "#", "##") }
