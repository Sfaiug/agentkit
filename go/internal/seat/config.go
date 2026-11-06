package seat

import (
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// ConfigSelection reads a seat's roles, following renames, with the same pruning as
// config.load_session. A seat made by hand has no saved models and takes the new seats' marks on c.
func ConfigSelection(name string) (*run.Object, error) {
	name, _, err := config.ResolveSession(name)
	if err != nil {
		return nil, err
	}
	path, err := config.SessionPath(name)
	if err != nil {
		return nil, err
	}
	data, err := run.ReadJSON(path)
	if data == nil {
		return nil, err
	}
	models, err := config.Models()
	if err != nil {
		return nil, err
	}
	return configSelection(data, models)
}

func configSelection(data *run.Object, models map[string]config.Model) (*run.Object, error) {
	bound, err := config.Bind()
	if err != nil {
		return nil, err
	}
	offered, err := config.Offered()
	if err != nil {
		return nil, err
	}
	read, ok := readsAsSeat(data, bound.Models, models, offered)
	if !ok {
		return nil, fmt.Errorf("saved roles cannot be read")
	}
	return read, nil
}

func recordCrew(record *run.Object, models map[string]config.Model) (string, string, bool) {
	if workers, ok := record.Get("workers").([]any); ok && len(workers) == 0 && record.Has("reviewers") {
		return "", "", true
	}
	return crew(record.Get("workers"), models)
}

// SaveMarks applies a mark to the current selection under Python's record lock, so another
// menu's changes survive it. A model the seat takes on gets its entry's efforts once.
func SaveMarks(name string, mark func(*run.Object) (*run.Object, string)) (*run.Object, error) {
	current, _, err := config.ResolveSession(name)
	if err != nil {
		return nil, err
	}
	models, err := config.Models()
	if err != nil {
		return nil, err
	}
	var saved *run.Object
	var selectionErr error
	err = update(filepath.Join(config.Home(), "state"), current, func(data *run.Object) bool {
		selected, err := configSelection(data, models)
		if err != nil {
			selectionErr = err
			return false
		}
		selected, note := mark(selected)
		if note != "" {
			selectionErr = fmt.Errorf("%s", note)
			return false
		}
		changed := set([]field{{"workers", selected.Get("workers")}, {"reviewers", selected.Get("reviewers")}})(data)
		if changed {
			ownEfforts(data, current, models)
		}
		saved = data.Copy()
		return changed
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
