package config

import (
	"fmt"
	"maps"
)

// EffortStep sets one role's effort. An unworded row follows the model's effort;
// a worker at that effort follows it too, as Python's menu._set_effort does. Each key of
// Hold that follows the effort keeps the one it followed, so a new effort leaves it in place.
type EffortStep struct {
	Model, Key, Effort string
	Hold               []string
}

func (s EffortStep) Apply(held map[string]string) map[string]string {
	next := maps.Clone(held)
	if next == nil {
		next = map[string]string{}
	}
	if effort, set := next["effort"]; set {
		for _, key := range s.Hold {
			if _, own := next[key]; !own {
				next[key] = effort
			}
		}
	}
	word := s.Effort
	if word == "" {
		word = next["effort"]
	}
	next[s.Key] = word
	for _, key := range append([]string{s.Key}, s.Hold...) {
		if key != "effort" && next[key] == next["effort"] {
			delete(next, key)
		}
	}
	return next
}

func recommendedEfforts(root *table, steps []EffortStep) error {
	for _, step := range steps {
		entry, _ := root.get("models").(*table).get(step.Model).(*table)
		if entry == nil {
			return fmt.Errorf("unknown model %q", step.Model)
		}
		held := map[string]string{}
		for _, key := range RoleEfforts {
			if word, ok := entry.get(key).(string); ok {
				held[key] = word
			}
		}
		next := step.Apply(held)
		for _, key := range RoleEfforts {
			if word, ok := next[key]; ok {
				entry.put(key, word)
			} else {
				delete(entry.values, key)
			}
		}
	}
	return nil
}
