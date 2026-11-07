package seat

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/tmux"
)

// moveRestarts is whether a move that is not in place (switchPane) starts a fresh conversation,
// the only restart Go carries: a kept conversation is left to Python.  A harness with no
// conversation can still restart on another of its models.
func moveRestarts(was, next config.Model, record map[string]any) bool {
	if was.Harness != next.Harness {
		return true
	}
	conversation, known := harness.Owned(was.Harness, record)
	return known && conversation == ""
}

// switchPane is the launch's own pane where the seat's running harness takes `next` from its
// `[switch]` lines rather than from a launch (orch.switch_lines): the same harness, the same
// provider unless it keeps one login a provider, a `model` line, an id of its own, that pane
// still running and its plugin taking that id at `next`'s effort there (harness.Switchable); ""
// where the move restarts the seat.
func switchPane(name string, was, next config.Model) (string, error) {
	if was.Harness != next.Harness {
		return "", nil
	}
	block, err := config.Section(next.Harness, "switch")
	if err != nil {
		return "", err
	}
	auth, err := config.Section(next.Harness, "auth")
	if err != nil {
		return "", err
	}
	if block["model"] == nil || next.ID == "" || next.ID == "default" ||
		was.Provider != next.Provider && auth["accounts"] != false {
		return "", nil
	}
	// the launch's own pane: once it is gone, another window's says nothing of the harness
	pane := harnessPane(name)
	if !paneName.MatchString(pane) {
		return "", nil
	}
	if dead, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", pane, "#{pane_dead}"); err != nil || dead != "0" ||
		!harness.Switchable(next.Harness, next.ID, next.Efforts["effort"]) {
		return "", nil
	}
	return pane, nil
}
