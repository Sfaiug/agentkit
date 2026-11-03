package seat

import (
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// keepEfforts is config.keep_efforts of every seat's record, what Python's save does before it
// writes config.toml: each record holds, under its lock, the efforts of the models it runs as
// they read now, so a change to their entries moves no seat.  A record that does not read as a
// seat's is left as it is.  `inFile` is every [models.*] table, `offered` the models load() offers.
func keepEfforts(state string, inFile []string, models map[string]config.Model, offered []string) error {
	for _, path := range config.SeatRecords("session") {
		name := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), "session-"), ".json")
		err := update(state, name, func(data *run.Object) bool {
			read, ok := readsAsSeat(data, inFile, models, offered)
			if !ok {
				return false
			}
			ownEfforts(read, name, models)
			if run.Equal(read.Get("efforts"), data.Get("efforts")) {
				return false
			}
			data.Set("efforts", read.Get("efforts"))
			return true
		})
		if err != nil {
			return err
		}
	}
	return nil
}

// readsAsSeat is the record as config._validate_session reads it with prune: a model no longer in
// the file passed over, a list that empties falling back to the first model offered, and
// executors written empty beside reviewers kept empty; false where it refuses the record.
func readsAsSeat(data *run.Object, inFile []string, models map[string]config.Model, offered []string) (*run.Object, bool) {
	runs := func(name string) bool { _, ok := models[name]; return ok }
	orchestrator, named := data.Get("orchestrator").(string)
	if !named || slices.Contains(inFile, orchestrator) && !runs(orchestrator) {
		return nil, false
	}
	read := data.Copy()
	for _, role := range []string{"workers", "reviewers"} {
		if role == "reviewers" && !data.Has(role) {
			continue
		}
		listed, isList := data.Get(role).([]any)
		if !isList || len(listed) == 0 && (role == "reviewers" || !data.Has("reviewers")) {
			return nil, false
		}
		group, kept := []any{}, []any{}
		for _, each := range listed {
			name, ok := each.(string)
			if !ok || slices.Contains(inFile, name) && !runs(name) || slices.Contains(group, each) {
				return nil, false
			}
			group = append(group, name)
			if slices.Contains(offered, name) {
				kept = append(kept, name)
			}
		}
		if len(offered) > 0 && len(group) > 0 {
			group = kept
			if len(group) == 0 {
				group = []any{offered[0]}
			}
		}
		for _, name := range group {
			if !runs(name.(string)) {
				return nil, false
			}
		}
		read.Set(role, group)
	}
	efforts := read.Dict("efforts")
	if read.Has("efforts") && (efforts == nil || slices.ContainsFunc(efforts.Keys(), func(model string) bool {
		held := efforts.Dict(model)
		if held == nil {
			return true
		}
		_, worded := held.Get("effort").(string)
		return !worded
	})) {
		return nil, false
	}
	return read, true
}
