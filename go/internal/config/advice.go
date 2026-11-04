package config

import (
	"fmt"
	"maps"
)

// EffortStep sets one role's effort. An unworded row follows the model's effort;
// a worker at that effort follows it too, as Python's menu._set_effort does.
type EffortStep struct{ Model, Key, Effort string }

func (s EffortStep) Apply(held map[string]string) map[string]string {
	next := maps.Clone(held)
	if next == nil {
		next = map[string]string{}
	}
	word := s.Effort
	if word == "" {
		word = next["effort"]
	}
	next[s.Key] = word
	if s.Key != "effort" && word == next["effort"] {
		delete(next, s.Key)
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
