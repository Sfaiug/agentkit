package seat

import (
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// audit is the weekly audit's seat (audit.NAME), whose models run at their entries' efforts.
const audit = "audit"

// A move is what a seat's last answer moves in its record (watch.follow_model): the
// configured model the answer ran on, the seat's own first, and that model's orchestrator effort
// where the answer ran at another it takes; "" for none.
type move struct{ chosen, effort string }

// follows is the move of a record's last answer: `/model` or `/effort` typed in the seat moves
// it as a move on `c` would. False where Python's answer hangs on a configured model or a
// manifest this reading cannot read.
func follows(record *run.Object, models map[string]config.Model, offered []string) (move, bool) {
	kept := record.Str("orchestrator")
	own := models[kept]
	model, effort, answered := harness.LastAnswer(own.Harness, record.Str("conversation"), record.Str("cwd"))
	if own.ID == "" || own.ID == "default" || !answered {
		return move{}, true
	}
	var runs []string
	for _, each := range append([]string{kept}, offered...) {
		entry, resolved := models[each]
		if !resolved {
			return move{}, false
		}
		if entry.Harness == own.Harness && model == any(entry.ID) {
			runs = append(runs, each)
		}
	}
	if len(runs) == 0 {
		return move{}, true
	}
	chosen := runs[0]
	if at := slices.IndexFunc(runs, func(each string) bool { return effort == any(models[each].Efforts["effort"]) }); at >= 0 {
		chosen = runs[at]
	}
	if effort == any(models[chosen].Efforts["effort"]) {
		return move{chosen, ""}, true
	}
	takes, err := config.Efforts(own.Harness, model.(string))
	if err != nil {
		return move{}, false
	}
	if word, named := effort.(string); named && slices.Contains(takes, word) {
		return move{chosen, word}, true
	}
	return move{chosen, ""}, true
}

// moved writes into the record what its last answer moved: its orchestrator, through
// config.update_session, which gives each model the seat then runs its entry's efforts, then
// that model's orchestrator effort, through config.change_efforts.
func (seat Seat) moved(state string, models map[string]config.Model) error {
	path, held := filepath.Join(state, "session-"+seat.Name+".json"), filepath.Join(state, ".session-"+seat.Name+".lock")
	to := seat.follow
	if to.chosen != "" && to.chosen != seat.Orchestrator {
		orchestrate := set([]field{{"orchestrator", to.chosen}})
		if err := put(path, held, run.Encode, func(data *run.Object) bool {
			if !orchestrate(data) {
				return false
			}
			ownEfforts(data, seat.Name, models)
			return true
		}); err != nil {
			return err
		}
	}
	if to.effort == "" {
		return nil
	}
	return put(path, held, run.Encode, func(data *run.Object) bool {
		efforts := orchestratingAt(data, to.chosen, to.effort, models)
		if run.Equal(efforts, data.Get("efforts")) {
			return false
		}
		data.Set("efforts", efforts)
		return true
	})
}

// ownEfforts is config.own_efforts: each model the record runs that it holds no efforts for
// takes its entry's, once, so an entry changed since moves no seat; the audit seat's go on with
// the entries'.
func ownEfforts(data *run.Object, name string, models map[string]config.Model) {
	held := data.Dict("efforts")
	if held == nil {
		held = run.NewObject()
	}
	efforts := held.Copy()
	runs := append(append([]any{data.Get("orchestrator")}, data.List("workers")...), data.List("reviewers")...)
	for _, each := range runs {
		model, named := each.(string)
		if entry, known := models[model]; named && known && !held.Has(model) {
			efforts.Set(model, entryEfforts(entry))
		}
	}
	if name != audit && len(efforts.Keys()) > len(held.Keys()) {
		data.Set("efforts", efforts)
	}
}

// orchestratingAt is config.orchestrating_at: the record's efforts with that model's orchestrator
// effort at `word`, every key it holds kept, one that followed it set where it stood, and a
// model it holds none for starting from its entry's.
func orchestratingAt(data *run.Object, model, word string, models map[string]config.Model) *run.Object {
	efforts := run.NewObject()
	if held := data.Dict("efforts"); held != nil {
		efforts = held.Copy()
	}
	own := efforts.Dict(model)
	if !efforts.Truthy(model) || own == nil {
		own = entryEfforts(models[model])
	}
	next := run.NewObject()
	for _, key := range config.RoleEfforts {
		next.Set(key, own.Get("effort"))
	}
	for _, key := range own.Keys() {
		next.Set(key, own.Get(key))
	}
	next.Set("effort", word)
	efforts.Set(model, next)
	return efforts
}

// entryEfforts is config.efforts_of: the efforts an entry sets, by their keys.
func entryEfforts(entry config.Model) *run.Object {
	efforts := run.NewObject()
	for _, key := range config.RoleEfforts {
		if word, set := entry.Efforts[key]; set {
			efforts.Set(key, word)
		}
	}
	return efforts
}
