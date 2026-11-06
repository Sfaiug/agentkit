package seat

import (
	"maps"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	script "agentkit/internal/transcript"
)

// audit is the weekly audit's seat (audit.NAME), whose models run at their entries' efforts.
const audit = "audit"

// A move is what a seat's last answer moves in its record (watch.follow_model): the
// configured model the answer ran on, the seat's own first, and that model's orchestrator effort
// where the answer ran at another it takes; "" for none. It is the answer made `at` of the
// conversation in the directory it was read from: Python decides under the seat's announce
// lock, so a record naming another by then, or one that answer no longer counts for, is not
// this move's.
type move struct {
	chosen, effort, conversation, cwd string
	at                                float64
}

// follows is the move of a record's last answer: `/model` or `/effort` typed in the seat moves
// it as a move on `c` would, where that answer counts. The models run at the efforts the
// record holds for them. False where Python's answer hangs on a configured model or a manifest
// this reading cannot read.
func follows(record, file *run.Object, models map[string]config.Model, offered []string, reader harness.Reader) (move, bool) {
	kept, conversation, cwd := record.Str("orchestrator"), record.Str("conversation"), record.Str("cwd")
	own := models[kept]
	model, effort, answeredAt, answered := reader.LastAnswer(record)
	at := script.Moment(answeredAt)
	if own.ID == "" || own.ID == "default" || !answered || !counts(at, record, file) {
		return move{}, true
	}
	models = atEfforts(models, record)
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
	to := move{chosen: chosen, conversation: conversation, cwd: cwd, at: at}
	if effort == any(models[chosen].Efforts["effort"]) {
		return to, true
	}
	takes, err := config.Efforts(own.Harness, model.(string))
	if err != nil {
		return move{}, false
	}
	if word, named := effort.(string); named && slices.Contains(takes, word) {
		to.effort = word
	}
	return to, true
}

// counts is whether an answer made at that moment moves the record: only one made since the
// harness was launched (`launched`) or a move in place went in (the seat file's `switched`), and
// none while a move is still owed (a `switch` among its owed lines), so the old model's last
// answer undoes no move.
func counts(at float64, record, file *run.Object) bool {
	if file == nil {
		return since(at, record.Get("launched"))
	}
	for _, line := range file.List("owed_lines") {
		if owed, _ := line.(*run.Object); owed != nil && owed.Truthy("switch") {
			return false
		}
	}
	return since(at, record.Get("launched"), file.Get("switched"))
}

// since is whether a moment is later than each of those that are moments.
func since(at float64, bounds ...any) bool {
	for _, bound := range bounds {
		if moment, dated := run.Num(bound); dated && !(at > moment) {
			return false
		}
	}
	return true
}

// atEfforts is config.at_efforts: the models as the record runs them, each it holds efforts for
// at those, every other at its entry's own.
func atEfforts(models map[string]config.Model, record *run.Object) map[string]config.Model {
	held := record.Dict("efforts")
	if held == nil {
		return models
	}
	models = maps.Clone(models)
	for _, name := range held.Keys() {
		entry, known := models[name]
		own := held.Dict(name)
		if !known || own == nil {
			continue
		}
		entry.Efforts = map[string]string{}
		for _, key := range own.Keys() {
			if word, named := own.Get(key).(string); named {
				entry.Efforts[key] = word
			}
		}
		models[name] = entry
	}
	return models
}

// moved writes into the record what its last answer moved: its orchestrator, through
// config.update_session, which gives each model the seat then runs its entry's efforts, then
// that model's orchestrator effort, through config.change_efforts.
func (seat Seat) moved(state string, models map[string]config.Model) error {
	to := seat.follow
	if to.chosen == "" {
		return nil
	}
	file, _ := run.ReadJSON(filepath.Join(state, "seat-"+seat.Name+".json"))
	// the record the answer was read from, run by that orchestrator by then, that it still counts for
	read := func(data *run.Object, orchestrator string) bool {
		return data.Str("orchestrator") == orchestrator && data.Str("conversation") == to.conversation && data.Str("cwd") == to.cwd &&
			counts(to.at, data, file)
	}
	if to.chosen != seat.Orchestrator {
		orchestrate := set([]field{{"orchestrator", to.chosen}})
		if err := update(state, seat.Name, func(data *run.Object) bool {
			if !read(data, seat.Orchestrator) || !orchestrate(data) {
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
	return update(state, seat.Name, func(data *run.Object) bool {
		efforts := orchestratingAt(data, to.chosen, to.effort, models)
		if !read(data, to.chosen) || run.Equal(efforts, data.Get("efforts")) {
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
