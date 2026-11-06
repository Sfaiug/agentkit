package matrix

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Configuration is c's one matrix of configured models and their role marks. The menu
// draws it; keys propose a selection here before a caller saves it to its own scope.
type Configuration struct {
	Names    []string
	Models   map[string]config.Model
	Levels   map[string][]string
	Selected *run.Object
}

func Configured() (*Configuration, error) {
	names, err := config.Offered()
	if err != nil {
		return nil, err
	}
	models, err := config.Models()
	if err != nil {
		return nil, err
	}
	defaults, err := config.Defaults()
	if err != nil {
		return nil, err
	}
	selected := run.NewObject()
	selected.Set("orchestrator", defaults.Orchestrator)
	selected.Set("workers", stringsAny(defaults.Workers))
	if defaults.Reviewers != nil {
		selected.Set("reviewers", stringsAny(defaults.Reviewers))
	}
	found := &Configuration{names, models, map[string][]string{}, selected}
	for _, name := range names {
		entry := models[name]
		if found.Levels[name], err = config.Efforts(entry.Harness, entry.ID); err != nil {
			return nil, err
		}
	}
	return found, nil
}

func stringsAny(names []string) []any {
	listed := []any{}
	for _, name := range names {
		listed = append(listed, name)
	}
	return listed
}

func (c *Configuration) Marks(name string) [3]bool {
	workers := c.Selected.List("workers")
	reviewers := workers
	if c.Selected.Has("reviewers") {
		reviewers = c.Selected.List("reviewers")
	}
	orch := c.Selected.Str("orchestrator") == name
	return [3]bool{orch, slices.Contains(workers, any(name)) || len(workers) == 0 && orch, slices.Contains(reviewers, any(name))}
}

func (c *Configuration) Columns(name string) []int { return Stops(c.Marks(name)) }

// Stops is where the keys stop along a model's row: each role's mark, then the effort beside a
// marked role, on c and on a new seat's models screen alike.
func Stops(marks [3]bool) []int {
	columns := []int{}
	for role, marked := range marks {
		columns = append(columns, role)
		if marked {
			columns = append(columns, role+3)
		}
	}
	return columns
}

func (c *Configuration) Effort(name string, role int) string {
	entry := c.Models[name]
	efforts := entry.Efforts
	if held := c.Selected.Dict("efforts"); held != nil && held.Dict(name) != nil {
		efforts = map[string]string{}
		for _, key := range config.RoleEfforts {
			if value, ok := held.Dict(name).Get(key).(string); ok {
				efforts[key] = value
			}
		}
	}
	if effort, set := efforts[config.RoleEfforts[role]]; set {
		return effort
	}
	return efforts["effort"]
}

// Mark captures the intended state from the displayed selection and merges just that
// model's mark into a current selection, preserving the other marks.
func (c *Configuration) Mark(name string, role int) func(*run.Object) (*run.Object, string) {
	key := []string{"orchestrator", "workers", "reviewers"}[role]
	group := c.Selected.List(key)
	if role == 2 && !c.Selected.Has(key) {
		group = c.Selected.List("workers")
	}
	marked := !slices.Contains(group, any(name))
	return func(current *run.Object) (*run.Object, string) {
		changed := current.Copy()
		if !changed.Has("reviewers") {
			changed.Set("reviewers", slices.Clone(changed.List("workers")))
		}
		if role == 0 {
			changed.Set("orchestrator", name)
			return changed, ""
		}
		group := slices.Clone(changed.List(key))
		at := slices.Index(group, any(name))
		if marked && at < 0 {
			group = append(group, name)
		} else if !marked && at >= 0 {
			if role == 2 && len(group) == 1 {
				return nil, "at least one model reviews"
			}
			group = slices.Delete(group, at, at+1)
		}
		changed.Set(key, group)
		return changed, ""
	}
}
