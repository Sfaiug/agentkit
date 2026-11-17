package seat

import (
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// SaveEfforts sets each of steps on the seat's efforts as they stand, under Python's record lock,
// in one write (menu.efforts_saved).  The seat's orchestrator effort is the one its harness runs,
// which Move moves.
func SaveEfforts(name string, steps ...Step) (*run.Object, error) {
	current, _, err := config.ResolveSession(name)
	if err != nil {
		return nil, err
	}
	models, err := config.Models()
	if err != nil {
		return nil, err
	}
	var saved *run.Object
	err = update(filepath.Join(config.Home(), "state"), current, func(data *run.Object) bool {
		changed := false
		for _, step := range steps {
			changed = step.on(data, models[step.Model]) || changed
		}
		saved = data.Copy()
		return changed
	})
	if err == nil && saved == nil {
		err = fmt.Errorf("%s has no saved models", name)
	}
	return saved, err
}

// A Step is Model's own Key at Effort; a role's, `exec_effort` or `review_effort`, at "" or at the
// effort following its effort, and the effort's own moving none of its other keys, as Move moves
// none (Python's menu._stepped).
type Step struct{ Model, Key, Effort string }

// on sets step on data's efforts, the model's own where it holds them, else entry's: whether that
// changed them.
func (step Step) on(data *run.Object, entry config.Model) bool {
	efforts := run.NewObject()
	if held := data.Dict("efforts"); held != nil {
		efforts = held.Copy()
	}
	own := entryEfforts(entry)
	if held := efforts.Dict(step.Model); held != nil {
		own = held.Copy()
	}
	keys := []string{step.Key}
	if step.Key == "effort" {
		keys = config.RoleEfforts
		for _, key := range keys {
			if !own.Has(key) && own.Has("effort") {
				own.Set(key, own.Get("effort"))
			}
		}
	}
	own.Set(step.Key, step.Effort)
	for _, key := range keys {
		if key != "effort" && own.Has(key) && (own.Str(key) == "" || own.Str(key) == own.Str("effort")) {
			own.Delete(key)
		}
	}
	efforts.Set(step.Model, own)
	changed := !run.Equal(efforts, data.Get("efforts"))
	data.Set("efforts", efforts)
	return changed
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
