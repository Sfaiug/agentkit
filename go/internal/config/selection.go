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
	return audit(root)
}

// audit is Audit of a config read, refusing what config.audit refuses in its order and words, so
// `c`, its page and the tick say the same thing.
func audit(root *table) (Selection, bool, error) {
	held := selection(root)
	if held.Reviewers == nil {
		held.Reviewers = held.Workers
	}
	on := true
	value := root.get("audit")
	if value == nil {
		value = newTable()
	}
	audit, ok := value.(*table)
	if !ok {
		return held, on, fmt.Errorf("~/.agentkit/config.toml: [audit] must be a table")
	}
	if value := audit.get("on"); value != nil {
		if on, ok = value.(bool); !ok {
			return held, true, fmt.Errorf("~/.agentkit/config.toml: [audit].on must be true or false (got %s)", valueRepr(value))
		}
	}
	for _, key := range []string{"workers", "reviewers"} {
		value := audit.get(key)
		if value == nil {
			continue
		}
		list, ok := value.([]any)
		names := []string{}
		for _, item := range list {
			name, named := item.(string)
			ok, names = ok && named, append(names, name)
		}
		if !ok {
			return held, on, fmt.Errorf("~/.agentkit/config.toml: [audit].%s must list model names (got %s)", key, valueRepr(value))
		}
		if key == "workers" {
			held.Workers = names
		} else {
			held.Reviewers = names
		}
	}
	if value := audit.get("orchestrator"); value != nil {
		if held.Orchestrator, ok = value.(string); !ok {
			return held, on, fmt.Errorf("~/.agentkit/config.toml: [audit].orchestrator must be a model name (got %s)", valueRepr(value))
		}
	}
	if len(held.Reviewers) == 0 {
		return held, on, fmt.Errorf("~/.agentkit/config.toml: [audit].reviewers must name a model")
	}
	for _, name := range append(append([]string{held.Orchestrator}, held.Workers...), held.Reviewers...) {
		if _, err := resolve(root, name); err != nil {
			return held, on, err
		}
	}
	return held, on, nil
}

// DoneCheck reads `[done_check]` as `c`'s row says it (done_check.setting): the model that makes
// the check, "" for the seat's reviewer, and whether it is on, true until written false.
func DoneCheck() (string, bool, error) {
	root, err := load()
	if err != nil {
		return "", false, err
	}
	return doneCheck(root)
}

// doneCheck is DoneCheck of a config read.
func doneCheck(root *table) (string, bool, error) {
	value := root.get("done_check")
	if value == nil {
		return "", true, nil
	}
	check, ok := value.(*table)
	if !ok {
		return "", true, fmt.Errorf("~/.agentkit/config.toml: [done_check] must be a table")
	}
	named, on := "", true
	if value := check.get("on"); value != nil {
		if on, ok = value.(bool); !ok {
			return "", true, fmt.Errorf("~/.agentkit/config.toml: [done_check].on must be true or false (got %s)", valueRepr(value))
		}
	}
	if value := check.get("model"); value != nil {
		if named, ok = value.(string); !ok {
			return "", on, fmt.Errorf("~/.agentkit/config.toml: [done_check].model must be a model name (got %s)", valueRepr(value))
		}
		if _, err := resolve(root, named); err != nil {
			return named, on, err
		}
	}
	return named, on, nil
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
