package terminal

import (
	"slices"
	"strings"
)

// Crew opens with the seat's orchestrator, then names each model that builds or reviews once, in
// the order it first comes, with the work it does there in words every font draws; nothing where
// nobody is beside the orchestrator (menu.crew).
func Crew(orchestrator string, builds, reviews []string) string {
	if len(builds) == 0 && len(reviews) == 0 {
		return ""
	}
	roles := []struct {
		word   string
		models []string
	}{{"orchestrates", []string{orchestrator}}, {"builds", builds}, {"reviews", reviews}}
	var seen, parts []string
	for _, model := range slices.Concat([]string{orchestrator}, builds, reviews) {
		if slices.Contains(seen, model) {
			continue
		}
		seen = append(seen, model)
		var words []string
		for _, role := range roles {
			if slices.Contains(role.models, model) {
				words = append(words, role.word)
			}
		}
		parts = append(parts, Plain(model)+" "+strings.Join(words, ", "))
	}
	return strings.Join(parts, "   ")
}
