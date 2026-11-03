package seat

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/tmux"
)

// Visit is the menu's wait=True attach. Reopening a gone seat and recording a notice's first
// output baseline stay Python's; neither is an ordinary live-seat open.
func Visit(name string, dry bool, out, errOut io.Writer) (bool, error) {
	name, record, err := config.ResolveSession(name)
	if err != nil {
		return false, nil
	}
	held, exited, known := find(name, record)
	if !known {
		return false, nil
	}
	if dry {
		verb := "attach"
		if !held || exited {
			verb = "resume"
		}
		fmt.Fprintf(out, "would %s %s\n", verb, name)
		return true, nil
	}
	state := filepath.Join(config.Home(), "state")
	notice, err := run.ReadJSON(filepath.Join(state, "notify-"+name+".json"))
	if !held || exited || err != nil && !os.IsNotExist(err) || notice != nil {
		return false, nil
	}
	file, err := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	if err != nil && !os.IsNotExist(err) || file != nil && file.Dict("usage_refusal") != nil && file.Dict("usage_refusal").Truthy("told") {
		return false, nil
	}
	return true, attachTerminal(name, out, errOut, tmux.Visit)
}

func attachTerminal(name string, out, errOut io.Writer, hand func(string, string) error) error {
	if !terminal.Attachable() {
		return sayWhere(name, out)
	}
	if tmux.Inside(tmux.Own()) {
		if err := tmux.Switch(tmux.Own(), name); err != nil {
			return Refusal(fmt.Sprintf("cannot switch to the session %s: %v", name, err))
		}
		recordOpening(name, errOut)
		return nil
	}
	if term := tmux.Term(); term != "" {
		fmt.Fprintf(out, "note: this box has no terminfo for TERM=%s; tmux is run as %s\n", os.Getenv("TERM"), term)
		os.Setenv("TERM", term)
	}
	recordOpening(name, errOut)
	return hand(tmux.Own(), name)
}

func recordOpening(name string, errOut io.Writer) {
	state, now := filepath.Join(config.Home(), "state"), time.Now()
	if err := errors.Join(nextGeneration(state, name, now), writeSeat(state, name, []field{{"opened_at", seconds(now)}})); err != nil {
		fmt.Fprintf(errOut, "WARN could not record opening %s: %s\n", name, err)
	}
}
