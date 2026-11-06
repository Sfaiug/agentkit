package pick

import (
	"slices"
	"strings"
)

// Dry is why no pair can take up a resume, Python's resume_models when nothing is left: each
// executor's spent window as spent says it, once.
func (r *Rules) Dry(spent func(string) string) string {
	var reasons []string
	for _, name := range r.executors {
		if why := spent(name); why != "" && !slices.Contains(reasons, why) {
			reasons = append(reasons, why)
		}
	}
	said := "nothing is left to execute with a legal reviewer"
	if len(reasons) > 0 {
		said += ": " + strings.Join(reasons, "; ")
	}
	return said
}
