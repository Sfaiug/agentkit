package terminal

import (
	"slices"
	"strings"
)

// Crew names each role, then who is in it at the effort they run it at, in words every font draws;
// one "build and review" where both hold the same; never the orchestrator, whose row names it;
// nothing where nobody is beside the orchestrator (menu.crew).
func Crew(builds, reviews []string) string {
	type role struct {
		word   string
		models []string
	}
	roles := []role{{"build", builds}, {"review", reviews}}
	if slices.Equal(distinct(builds), distinct(reviews)) {
		roles = []role{{"build and review", builds}}
	}
	var parts []string
	for _, role := range roles {
		if len(role.models) == 0 {
			continue
		}
		var named []string
		for _, model := range role.models {
			named = append(named, Plain(model))
		}
		parts = append(parts, role.word+": "+strings.Join(named, ", "))
	}
	return strings.Join(parts, "   ")
}

// distinct is models as a set: sorted, each once.
func distinct(models []string) []string {
	return slices.Compact(slices.Sorted(slices.Values(models)))
}
