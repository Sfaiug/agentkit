package config

import "fmt"

// Selection is a set of role marks; absent reviewers follow the workers.
type Selection struct {
	Orchestrator       string
	Workers, Reviewers []string
}

func Defaults() (Selection, error) {
	root, err := load()
	if err != nil {
		return Selection{}, err
	}
	return selection(root), nil
}

func selection(root *table) Selection {
	defaults := root.get("defaults").(*table)
	orchestrator, _ := defaults.get("orchestrator").(string)
	workers, reviewers := groups(root)
	return Selection{orchestrator, workers, reviewers}
}

// Audit reads the weekly audit's overrides of the new seats' marks (config.audit).
func Audit() (Selection, bool, error) {
	root, err := load()
	if err != nil {
		return Selection{}, false, err
	}
	held := selection(root)
	if held.Reviewers == nil {
		held.Reviewers = held.Workers
	}
	on := true
	if value := root.get("audit"); value != nil {
		audit, ok := value.(*table)
		if !ok {
			return held, on, fmt.Errorf("[audit] must be a table")
		}
		if value := audit.get("on"); value != nil {
			if on, ok = value.(bool); !ok {
				return held, on, fmt.Errorf("[audit].on must be true or false")
			}
		}
		if value := audit.get("orchestrator"); value != nil {
			if held.Orchestrator, ok = value.(string); !ok {
				return held, on, fmt.Errorf("[audit].orchestrator must be a model name")
			}
		}
		for key, group := range map[string]*[]string{"workers": &held.Workers, "reviewers": &held.Reviewers} {
			if value := audit.get(key); value != nil {
				if !stringList(value, key == "reviewers") {
					return held, on, fmt.Errorf("[audit].%s must list model names", key)
				}
				*group = []string{}
				for _, name := range value.([]any) {
					*group = append(*group, name.(string))
				}
			}
		}
	}
	for _, name := range append(append([]string{held.Orchestrator}, held.Workers...), held.Reviewers...) {
		if _, err := resolve(root, name); err != nil {
			return held, on, err
		}
	}
	return held, on, nil
}

// HarnessLook is the name and colour declared by a plugin, never a screen's own list.
func HarnessLook(harness string) (name, colour string) {
	found, _ := manifests()
	name, _ = found[harness].get("name").(string)
	colour, _ = found[harness].get("colour").(string)
	if name == "" {
		name = harness
	}
	if !hexColour.MatchString(colour) {
		colour = "accent"
	}
	return
}
