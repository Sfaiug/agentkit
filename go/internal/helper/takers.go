package helper

import (
	"slices"

	"agentkit/internal/machines"
)

// takers are the machines that take work, "tests" or "turns", as Python's _takers: config.toml's
// and the suite helper, by their marks (machines.work), turns never on one whose probe last said
// macOS.
func takers(work string) []string {
	var aliases []string
	for _, machine := range machines.Known() {
		if marks, _ := machine.Work(); machine.Name != machines.Here && slices.Contains(marks, work) {
			aliases = append(aliases, machine.Name)
		}
	}
	return aliases
}
