package tick

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// wayBack is what a seat's pane left dead says, where tmux would say `Pane is dead` (orch.WAY_BACK).
const wayBack = "The harness ended. To open it again: Ctrl-b m, then this seat's number."

// hookOptions is the server hooks row (orch.set_hook_options): on ak's own server, which one started
// before them lacks, the options that run ak: what brings back a seat whose harness ended without
// ak ending it, and what puts the seat a client is in first.  Each verb is named by its program's
// path, as orch.hook_options names sys.executable: a server's own PATH may hold none.  `front` is
// this program's own.  `ended` is Python's, so it runs its bin/ak under the python3 this tick's
// PATH finds, the one bin/ak's `#!/usr/bin/env python3` runs Python's tick on.  A program that is
// that bin/ak itself, or finds none or no python3, leaves the row to Python.  A server that is not
// up, holding no session, gets nothing, and a set that fails is the next tick's to try again.
func hookOptions() error {
	if len(tmux.Sessions(tmux.Own())) == 0 {
		return nil
	}
	python, err := exec.LookPath("python3")
	if err != nil {
		return errLeft
	}
	if python, err = filepath.Abs(python); err != nil {
		return errLeft
	}
	bin := filepath.Join(config.Repo(), "bin", "ak")
	self, err := os.Executable()
	if err != nil {
		return errLeft
	}
	ours, err := os.Stat(self)
	theirs, missing := os.Stat(bin)
	if err != nil || missing != nil || os.SameFile(ours, theirs) {
		return errLeft
	}
	log := commandhelp.ShellJoin([]string{logPath()})
	job := func(program []string, verb string) string {
		ak := commandhelp.ShellJoin(append(program, "orch"))
		return "run-shell -b " + tmux.Word(tmuxText(ak)+" "+verb+" >>"+tmuxText(log)+" 2>&1; true")
	}
	front := job([]string{self}, "front")
	options := [][2]string{{"pane-died", job([]string{python, bin}, "ended #{q:session_name} #{pane_dead_time}")},
		{"remain-on-exit-format", wayBack},
		{"client-attached", front}, {"client-detached", front}, {"client-session-changed", front}}
	var lists [][]string
	for _, option := range options {
		lists = append(lists, []string{"set-option", "-gq", option[0], option[1]})
	}
	tmux.Lists(tmux.Own(), lists)
	return nil
}

// tmuxText is literal text for a tmux option, its `#`, which starts a format, doubled.
func tmuxText(text string) string { return strings.ReplaceAll(text, "#", "##") }
