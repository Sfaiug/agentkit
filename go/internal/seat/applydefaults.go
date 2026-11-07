package seat

import (
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Defaults is what `a` on a fresh window's `c` gives the seats (menu.apply_defaults): [defaults]'s
// orchestrator `lead`, the seats it applies to (`Open`), of those the ones not running lead at its
// entry's effort (`moving`), and of those the ones that restart for it (`Restarts`).
type Defaults struct {
	lead           string
	Open, Restarts []string
	moving         []string
}

// DefaultsMove is what `a` asks about: of the seats `rows` names, in their order, those with a
// record of their own but the weekly audit's, and of those the ones not running `lead` at its
// entry's effort that their running harness cannot move there in place (orch.switch_lines).
// False where Go cannot tell.
func DefaultsMove(rows []string, lead string) (Defaults, bool) {
	models, err := config.Models()
	entry, named := models[lead]
	skip, _, unread := config.ResolveSession(audit)
	if err != nil || !named || unread != nil {
		return Defaults{}, false
	}
	given := Defaults{lead: lead}
	for _, name := range rows {
		current, record, err := config.ResolveSession(name)
		if err != nil {
			return Defaults{}, false
		}
		if current != name || record == nil || name == skip { // a rename's pointer is no record
			continue
		}
		given.Open = append(given.Open, name)
		at, read := atOwnEfforts(entry, lead, record)
		if !read {
			return Defaults{}, false
		}
		was, _ := record["orchestrator"].(string)
		if was == lead && at.Efforts["effort"] == entry.Efforts["effort"] {
			continue
		}
		given.moving = append(given.moving, name)
		pane, err := switchPane(name, models[was], entry)
		if err != nil {
			return Defaults{}, false
		}
		if pane == "" {
			given.Restarts = append(given.Restarts, name)
		}
	}
	return given, true
}

// Apply is `Apply` picked on that card: every open seat takes [defaults]'s executors and
// reviewers and the entries' efforts for the models it then runs (defaultEfforts); each moving one
// then moves to lead at its entry's effort (Move), the only way a seat's orchestrator effort
// changes, so a move refused or failed leaves its record on the one its harness runs, its other
// changes kept; and each one's bar names what it took at once (Redress).  config.toml is not
// written.  What to say under the rows, one line a seat refused; false, before anything is
// written, where Go does not carry a seat's move.
func (given Defaults) Apply() (string, bool) {
	models, err := config.Models()
	bound, unbound := config.Bind()
	if err != nil || unbound != nil {
		return "", false
	}
	effort := models[given.lead].Efforts["effort"]
	moves := map[string]*plannedMove{}
	for _, name := range given.moving {
		plan, known := planMove(name, given.lead, effort)
		if !known {
			return "", false
		}
		moves[name] = plan
	}
	// reviewers [defaults] does not name follow the executors, there and here alike: the record
	// names none, rather than an empty list no seat reads
	named, reviewers := any(nil), bound.Workers
	if bound.Reviewers != nil {
		named, reviewers = bound.Reviewers, bound.Reviewers
	}
	taken := run.NewObject()
	for _, model := range slices.Concat([]any{given.lead}, bound.Workers, reviewers) {
		taken.Set(model.(string), entryEfforts(models[model.(string)]))
	}
	state := filepath.Join(config.Home(), "state")
	var said []string
	for _, name := range given.Open {
		err := update(state, name, func(data *run.Object) bool {
			before := data.Copy()
			fill(data, []field{{"efforts", defaultEfforts(data, taken, models)}, {"workers", bound.Workers}, {"reviewers", named}})
			return !run.Equal(before, data)
		})
		if err != nil {
			said = append(said, name+": "+config.Fold(err.Error()))
			continue
		}
		if plan := moves[name]; plan != nil {
			if _, err := plan.carry(func() (bool, bool) { return true, true }); err != nil {
				said = append(said, name+": "+config.Fold(err.Error()))
			}
		}
		Redress(name) // after the move, a restart's launch dressing a bar with no roles yet
	}
	return strings.Join(said, "\n"), true
}

// defaultEfforts is the record's efforts as `a` leaves them: those it holds, its orchestrator's
// entry's and `taken`'s over them, its orchestrator at the effort it runs at, which only a move at
// another changes.
func defaultEfforts(data, taken *run.Object, models map[string]config.Model) *run.Object {
	held, own := data.Dict("efforts"), data.Str("orchestrator")
	efforts := run.NewObject()
	if held != nil {
		efforts = held.Copy()
	}
	entry, named := models[own]
	if named {
		efforts.Set(own, entryEfforts(entry))
	}
	for _, model := range taken.Keys() {
		efforts.Set(model, taken.Get(model))
	}
	if !named {
		return efforts
	}
	at := entry.Efforts["effort"]
	if held != nil && held.Dict(own) != nil {
		at = held.Dict(own).Str("effort")
	}
	return orchestratingAt(run.Fields("efforts", efforts), own, at, models)
}
