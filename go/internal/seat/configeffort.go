package seat

import (
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// SaveEffort changes only a worker role's effort under Python's record lock. The seat's
// orchestrator effort needs a restart and must be handed over before anything is written.
func SaveEffort(name, model, key, word string) (*run.Object, error) {
	if key != "exec_effort" && key != "review_effort" {
		return nil, fmt.Errorf("the orchestrator effort needs a restart")
	}
	current, _, err := config.ResolveSession(name)
	if err != nil {
		return nil, err
	}
	entry, err := config.ModelNamed(model)
	if err != nil {
		return nil, err
	}
	var saved *run.Object
	err = update(filepath.Join(config.Home(), "state"), current, func(data *run.Object) bool {
		efforts := run.NewObject()
		if held := data.Dict("efforts"); held != nil {
			efforts = held.Copy()
		}
		own := entryEfforts(entry)
		if held := efforts.Dict(model); held != nil {
			own = held.Copy()
		}
		own.Set(key, word)
		if word == own.Str("effort") {
			own.Delete(key)
		}
		efforts.Set(model, own)
		changed := !run.Equal(efforts, data.Get("efforts"))
		data.Set("efforts", efforts)
		saved = data.Copy()
		return changed
	})
	if err == nil && saved == nil {
		err = fmt.Errorf("%s has no saved models", name)
	}
	return saved, err
}

// KeepConfigEfforts is Python's save's record preparation, before config.toml is replaced.
func KeepConfigEfforts() error {
	models, err := config.Models()
	if err != nil {
		return err
	}
	bound, err := config.Bind()
	if err != nil {
		return err
	}
	offered, err := config.Offered()
	if err != nil {
		return err
	}
	return keepEfforts(filepath.Join(config.Home(), "state"), bound.Models, models, offered)
}
