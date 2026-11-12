package helper

import (
	"slices"

	"agentkit/internal/machines"
)

// takers are the machines that take work, "tests" or "turns", as Python's _takers: config.toml's,
// the suite helper and the rentals that serve, by their marks (machines.work), turns never on one
// whose probe last said macOS, and never a rental that keeps a route but serves no more, even where
// config.toml names it.
func takers(work string) []string {
	var aliases []string
	for _, machine := range machines.Known() {
		if marks, _ := machine.Work(); machine.Name != machines.Here && machine.Serves() && slices.Contains(marks, work) {
			aliases = append(aliases, machine.Name)
		}
	}
	return aliases
}
