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
	block, err := config.Section(next.Harness, "switch")
	auth, unread := config.Section(next.Harness, "auth")
	if err != nil || unread != nil {
		return false
	}
	if block["model"] != nil && next.ID != "" && next.ID != "default" &&
		(was.Provider == next.Provider || auth["accounts"] == false) {
		pane, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", harnessPane(name), "#{pane_id} #{pane_dead}")
		id, dead, _ := strings.Cut(pane, " ")
		if err == nil && paneName.MatchString(id) && dead == "0" {
			return false
		}
	}
	conversation, known := harness.Owning(was.Harness, record)
	return known && conversation == ""
}
