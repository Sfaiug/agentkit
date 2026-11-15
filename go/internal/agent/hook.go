package agent

import (
	"os"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/tmux"
)

// Process is the words of that process's command and its parent's ID, as the `ps` reading every
// asker shares lists them (orch.processes): none, and itself for its parent, where it lists none.
// Only read the words: they are every asker's.
func Process(pid int) (words []string, parent int) {
	commands, children := processes(nil)
	if words, listed := commands[pid]; listed {
		for parent, kids := range children {
			if slices.Contains(kids, pid) {
				return words, parent
			}
		}
	}
	return nil, pid
}

// OwnsHook is whether the hook whose parent is pid comes from the client in the pane the seat's
// launch made, on that server (orch.owns_hook): every pane of the session inherits the seat's
// name, so the hook's pane must be the one the launch saved, and a nested client inherits even
// that pane, so from pid up to the pane's process exactly one process runs a client by client,
// none of them one that prints.
func OwnsHook(server, session string, pid int, client func(words []string) bool) bool {
	here, _, _ := strings.Cut(os.Getenv("TMUX"), ",")
	pane := os.Getenv("TMUX_PANE")
	if here == "" || pane == "" {
		return false
	}
	said, err := tmux.Ask(server, "display-message", "-p", "-t", pane,
		"#{socket_path}\t#{session_name}\t#{pane_pid}\t#{"+tmux.HarnessPane+"}")
	parts := strings.Split(said, "\t")
	if err != nil || len(parts) != 4 || parts[0] != here || parts[1] != session || parts[3] != pane {
		return false
	}
	root, err := strconv.Atoi(parts[2])
	commands, children := readProcesses()
	parents := map[int]int{}
	for parent, kids := range children {
		for _, kid := range kids {
			parents[kid] = parent
		}
	}
	clients := 0
	for seen := map[int]bool{}; err == nil && !seen[pid]; pid = parents[pid] {
		words, listed := commands[pid]
		if !listed {
			return false
		}
		seen[pid] = true
		if client(words) {
			if slices.Contains(words, "-p") || slices.Contains(words, "--print") {
				return false
			}
			clients++
		}
		if pid == root {
			return clients == 1
		}
	}
	return false
}
