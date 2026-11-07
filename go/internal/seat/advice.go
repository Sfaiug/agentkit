package seat

import (
	"fmt"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// SaveAdvice saves defaults and entries together, or a seat's groups and efforts together
// under its record lock. The seat's orchestrator is only said, never moved here.
func SaveAdvice(name string, selected *run.Object, steps []config.EffortStep) (*run.Object, error) {
	taken := []config.EffortStep{}
	for _, step := range steps {
		if name == "" || step.Key != "effort" {
			taken = append(taken, step)
		}
	}
	if len(taken) == 0 {
		return nil, fmt.Errorf("nothing to take: no configured model runs a take")
	}
	models, err := config.Models()
	if err != nil {
		return nil, err
	}
	for _, step := range taken {
		if _, known := models[step.Model]; !known {
			return nil, fmt.Errorf("unknown model %q", step.Model)
		}
	}
	groups := func(current *run.Object) (*run.Object, error) {
		next := current.Copy()
		if !next.Has("reviewers") {
			next.Set("reviewers", next.Get("workers"))
		}
		for _, step := range taken {
			switch step.Key {
			case "effort":
				next.Set("orchestrator", step.Model)
			case "exec_effort":
				next.Set("workers", []any{step.Model})
			case "review_effort":
				next.Set("reviewers", []any{step.Model})
			}
		}
		admitted := len(next.List("reviewers")) == 0
		for _, name := range next.List("reviewers") {
			entry, known := models[name.(string)]
			if !known {
				return nil, fmt.Errorf("unknown model %q", name)
			}
			allowed, err := config.CanReview(entry.Harness)
			if err != nil {
				return nil, err
			}
			admitted = admitted || allowed
		}
		if !admitted {
			return nil, fmt.Errorf("no allowed executor/reviewer pair")
		}
		return next, nil
	}
	state := filepath.Join(config.Home(), "state")
	if name == "" {
		bound, err := config.Bind()
		if err != nil {
			return nil, err
		}
		offered, err := config.Offered()
		if err != nil {
			return nil, err
		}
		next, err := groups(selected)
		if err != nil {
			return nil, err
		}
		names := func(key string) []string {
			var names []string
			for _, value := range next.List(key) {
				names = append(names, value.(string))
			}
			return names
		}
		err = savingEfforts(bound.Models, models, offered, tryLocks, func(keep func() error) error { // a busy record refuses the save intact
			return config.RememberDefaults(next.Str("orchestrator"), names("workers"), names("reviewers"), keep, taken...)
		})
		return next, err
	}
	current, _, err := config.ResolveSession(name)
	if err != nil {
		return nil, err
	}
	var saved *run.Object
	var selectionErr error
	err = update(state, current, func(data *run.Object) bool {
		selected, err := configSelection(data, models)
		if err != nil {
			selectionErr = err
			return false
		}
		next, err := groups(selected)
		if err != nil {
			selectionErr = err
			return false
		}
		ownEfforts(next, current, models)
		efforts := run.NewObject()
		if held := next.Dict("efforts"); held != nil {
			efforts = held.Copy()
		}
		for _, step := range taken {
			own := efforts.Dict(step.Model)
			if own == nil {
				own = entryEfforts(models[step.Model])
			}
			own = own.Copy()
			held := map[string]string{}
			for _, key := range config.RoleEfforts {
				if word, ok := own.Get(key).(string); ok {
					held[key] = word
				}
			}
			nextEfforts := step.Apply(held)
			for _, key := range config.RoleEfforts {
				if word, ok := nextEfforts[key]; ok {
					own.Set(key, word)
				} else {
					own.Delete(key)
				}
			}
			efforts.Set(step.Model, own)
		}
		next.Set("efforts", efforts)
		saved = next
		return set([]field{{"workers", next.Get("workers")}, {"reviewers", next.Get("reviewers")}, {"efforts", efforts}})(data)
	})
	if err == nil {
		err = selectionErr
	}
	if err == nil && saved == nil {
		err = fmt.Errorf("%s has no saved models", name)
	}
	if err == nil {
		Redress(current)
	}
	return saved, err
}

// Recommendation caches and temporary originals do not affect seat listings. Matrix cannot be imported here:
// its refresh reads the build through update, whose harness updates use seats.
func recommendationState(name string) bool {
	stem, suffix, _ := strings.Cut(name, ".")
	return strings.HasPrefix(name, adviceBackupPrefix) ||
		(stem == "boards" || stem == "matrix") && slices.Contains([]string{"json", "lock", "tmp"}, suffix)
}
