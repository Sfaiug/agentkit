package plan

import (
	"slices"
	"strings"
)

// Outcomes is the plan's verified work, independent of proof stamps, order and repetition.
// Deferred work needs Python's delivered-follow-up reader before it can be carded.
func Outcomes(name string) ([]any, error) {
	lines, err := read(name)
	if err != nil {
		return nil, err
	}
	work := map[string][]any{}
	for _, text := range lines {
		line, known := parse(text)
		if open(text) {
			continue
		}
		if known {
			if line.Deferred {
				return nil, ErrUnread
			}
			work[line.Project+"\x00"+line.What] = []any{line.Project, line.What}
		} else if text = strings.TrimSpace(text); strings.HasPrefix(text, "- [x] ") {
			work["\x00"+text[6:]] = []any{"", text[6:]}
		}
	}
	var keys []string
	for key := range work {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	out := []any{}
	for _, key := range keys {
		out = append(out, work[key])
	}
	return out, nil
}
