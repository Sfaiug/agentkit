package seat

import (
	"strings"

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
// provider, a `model` line, an id of its own and a pane that still runs.
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
	pane, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", harnessPane(name), "#{pane_id} #{pane_dead}")
	id, dead, _ := strings.Cut(pane, " ")
	return err == nil && paneName.MatchString(id) && dead == "0", nil
}
