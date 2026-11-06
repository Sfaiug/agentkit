package seat

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/tmux"
)

// moveRestarts leaves switch_in_place first, then a kept conversation, to Python.
// A harness with no conversation can still restart on another of its models.
func moveRestarts(name string, was, next config.Model, record map[string]any) bool {
	if was.Harness != next.Harness {
		return true
	}
	if inPlace, err := switchesInPlace(name, was, next); err != nil || inPlace {
		return false
	}
	conversation, known := harness.Owned(was.Harness, record)
	return known && conversation == ""
}

// switchesInPlace is whether the seat's running harness takes `next` from its `[switch]` lines
// rather than from a launch (orch.switch_lines), its plugin's own say aside
// (harness.AsksSwitchable): the same harness, the same provider unless it keeps one login a
// provider, a `model` line, an id of its own and the launch's pane still running.
func switchesInPlace(name string, was, next config.Model) (bool, error) {
	if was.Harness != next.Harness {
		return false, nil
	}
	block, err := config.Section(next.Harness, "switch")
	if err != nil {
		return false, err
	}
	auth, err := config.Section(next.Harness, "auth")
	if err != nil {
		return false, err
	}
	if block["model"] == nil || next.ID == "" || next.ID == "default" ||
		was.Provider != next.Provider && auth["accounts"] != false {
		return false, nil
	}
	// the launch's own pane: once it is gone, another window's says nothing of the harness
	pane := harnessPane(name)
	if !paneName.MatchString(pane) {
		return false, nil
	}
	dead, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", pane, "#{pane_dead}")
	return err == nil && dead == "0", nil
}
