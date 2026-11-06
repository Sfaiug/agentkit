package notify

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lifecycle"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// standing is whether a client is attached to the seat, and whether Go knows its word, which
// Python's session_state decides: `needs you`, the question asked now standing, for a name no
// tmux session holds, with or without a record, and for a seat ak's server holds alive with no look, run or
// outstanding watch work, whose word no hook fact or turn's latch decides, on a harness whose chat Python
// does not read for the question (none `nudge`s).
func standing(name string, record map[string]any) (attached, known bool) {
	exists := func(path string) bool { _, err := os.Lstat(path); return !errors.Is(err, fs.ErrNotExist) }
	if path, _ := config.SessionPath(name); record == nil && exists(path) {
		return false, false // a record that is no object
	}
	if exists(seatFile("seat", name, "json")) || exists(filepath.Join(state(), "watch.json")) && (record == nil || !quietWatch()) {
		return false, false
	}
	if runs, err := os.ReadDir(run.Runs()); len(runs) > 0 || err != nil && !errors.Is(err, fs.ErrNotExist) {
		return false, false
	}
	if record != nil {
		orchestrator, _ := record["orchestrator"].(string)
		model, err := config.ModelNamed(orchestrator)
		if err != nil {
			return false, false
		}
		if nudged, err := lifecycle.Nudged(model.Harness); err != nil || nudged {
			return false, false
		}
	}
	panes, _ := tmux.Ask(tmux.Own(), "list-panes", "-a", "-F", "#{session_attached}\t#{pane_dead}\t#{session_name}")
	found, alive := false, false
	for _, line := range config.SplitLines(panes) {
		clients, rest, _ := strings.Cut(line, "\t")
		dead, session, _ := strings.Cut(rest, "\t")
		if session != config.Control && config.Fold(session) == name {
			found, alive, attached = true, alive || dead != "1", clients != "" && clients != "0"
		}
	}
	if found {
		return attached, record != nil && alive
	}
	legacy := slices.ContainsFunc(tmux.Sessions(tmux.Default), func(session tmux.Session) bool {
		return session.Mark == "1" && config.Fold(session.Name) == name
	})
	return false, !legacy
}
