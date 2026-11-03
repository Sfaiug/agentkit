package config

import "slices"

// BindSeat is the Binding a seat's own launch records, as Python's capture_launch binds it from
// config.load_session: the seat record's workers, and its reviewers where it names any, each model
// at the efforts the record holds for it, every other at its entry's own (config.run_efforts).  A
// record Python reads otherwise is errUnbound: a list naming a model the config does not offer,
// which load_session passes over or falls back from, a list empty or repeating a name, or efforts
// load_session refuses.
func BindSeat(record map[string]any) (Binding, error) {
	bound, err := Bind()
	if err != nil {
		return Binding{}, err
	}
	offered, err := Offered()
	if err != nil {
		return Binding{}, err
	}
	listed := func(role string) ([]any, bool) {
		names, ok := record[role].([]any)
		for at, name := range names {
			if name, named := name.(string); !named || !slices.Contains(offered, name) || slices.Contains(names[:at], any(name)) {
				return nil, false
			}
		}
		return names, ok && len(names) > 0
	}
	var whole bool
	if bound.Workers, whole = listed("workers"); !whole {
		return Binding{}, errUnbound
	}
	bound.Reviewers = nil
	if _, named := record["reviewers"]; named {
		if bound.Reviewers, whole = listed("reviewers"); !whole {
			return Binding{}, errUnbound
		}
	}
	held, _ := record["efforts"].(map[string]any)
	if _, set := record["efforts"]; set && held == nil {
		return Binding{}, errUnbound
	}
	for name, value := range held {
		own, _ := value.(map[string]any)
		if _, named := own["effort"].(string); !named {
			return Binding{}, errUnbound
		}
		if !slices.Contains(bound.Models, name) {
			continue
		}
		var efforts [][2]string
		for _, key := range RoleEfforts {
			if word, set := own[key]; set {
				word, named := word.(string)
				if !named {
					return Binding{}, errUnbound
				}
				efforts = append(efforts, [2]string{key, word})
			}
		}
		bound.Efforts[name] = efforts
	}
	return bound, nil
}
