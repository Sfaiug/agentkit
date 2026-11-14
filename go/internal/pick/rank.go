package pick

import (
	"maps"
	"slices"

	"agentkit/internal/config"
)

// A Ranker compares two of names as Python's matrix.rank places them off the lineup `ak models`
// last stored, for executing or with review reviewing, each run as models has it, at its effort for
// the role; 0 for an equal place.  The role's pick is chosen in names' order.
type Ranker func(review bool, models map[string]config.Model, names []string) func(a, b string) int

// Lineup is what a pick reads of the lineup `ak models` last stored, matrix's ranking, which
// matrix supplies, as it reads that lineup through packages that import this one: its Ranker and
// the models off in the model list, false where that list cannot be read.
var Lineup func() (Ranker, map[string]bool, bool)

// OffList is why a pick leaves out a model off in the model list, Python's matrix.OFF.
const OffList = "off in the model list"

// At is these Rules with each model of their groups as model has it, Python's picks off
// config.at_efforts: a round's picks rank each model at the efforts the run launched with
// (loop.model), later edits aside.  false where model refuses one.
func (r *Rules) At(model func(name string) (config.Model, error)) (*Rules, bool) {
	at := *r
	at.models = maps.Clone(r.models)
	for _, name := range append(slices.Clone(r.executors), r.reviewList...) {
		found, err := model(name)
		if err != nil {
			return nil, false
		}
		at.models[name] = found
	}
	return &at, true
}
