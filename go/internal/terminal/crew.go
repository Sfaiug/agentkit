package terminal

import (
	"slices"
	"strings"
)

// Crew names each model once, in the order it first comes, with the work it does.
func (s Screen) Crew(builds, reviews []string) string {
	build, review := "⚒", "◎"
	if s.ASCII() {
		build, review = "B", "R"
	}
	var seen, parts []string
	for _, model := range slices.Concat(builds, reviews) {
		if slices.Contains(seen, model) {
			continue
		}
		seen = append(seen, model)
		icons := ""
		if slices.Contains(builds, model) {
			icons += build
		}
		if slices.Contains(reviews, model) {
			icons += review
		}
		parts = append(parts, Plain(model)+" "+icons)
	}
	return strings.Join(parts, "   ")
}
