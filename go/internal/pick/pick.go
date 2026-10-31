// Package pick holds the rules that choose a run's models from what a usage read says of them,
// Python's usage.pick_order and the staffing rules review_pair calls: the models with room for a
// role, ranked by the budget they have left, and the pair a run takes, a reviewer on another
// provider first, then another model, then the executor's own.  It never reads a meter: a read
// answers it through Room.
package pick

import (
	"os"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// Room is what a pick asks a usage read of each model.
type Room interface {
	// Spent is whether nothing is picked on it: a meter gating it spent, or its provider parked.
	Spent(model string) bool
	// Budget is its budget, false where its reading cannot tell.
	Budget(model string) (float64, bool)
	// OnCredits is whether it runs on credits past a spent window.
	OnCredits(model string) bool
}

// Rules are config.toml's groups, as a pick outside any seat reads them.
type Rules struct {
	executors, reviewers []string
	models               map[string]config.Model
}

// Load is the home's Rules, false where Python ak picks there: a seat's own groups, a payg
// provider or model, one whose harness says how it is paid, a pace_margin Python refuses, a model a group names that config.model refuses, a
// matrix lineup from state/matrix.json that ranks the models, are not yet Go's.
func Load() (*Rules, bool) {
	if _, seat, err := config.CurrentSession(); err != nil || seat != nil {
		return nil, false
	}
	if _, ok := config.PaceMargin(); !ok || ranked() {
		return nil, false
	}
	executors, reviewers, err := config.Groups()
	if err != nil {
		return nil, false
	}
	models, err := config.Models()
	subs, failed := config.Subscriptions()
	if err != nil || failed != nil {
		return nil, false
	}
	for _, sub := range subs {
		if sub.Mode == "payg" {
			return nil, false
		}
	}
	if reviewers == nil {
		reviewers = executors
	}
	for _, name := range append(slices.Clone(executors), reviewers...) {
		if model, ok := models[name]; !ok || model.Mode == "payg" || harness.PaysItsOwnWay(model.Harness) {
			return nil, false
		}
	}
	rules := &Rules{executors: executors, models: models}
	for _, name := range reviewers {
		// a harness that loads the checkout's own instructions would judge a branch by its rules
		files, err := config.Words(models[name].Harness, "instructions", "workspace")
		if err != nil {
			return nil, false
		}
		if !slices.ContainsFunc(files, func(file string) bool { return file != "" }) {
			rules.reviewers = append(rules.reviewers, name)
		}
	}
	return rules, true
}

// Order is the models with room for a role, executors or with review reviewers, Python's
// usage.pick_order: one on credits after every one with a window left, an unknown budget after
// every known one, then the most budget first, else the order config.toml lists them in.
func (r *Rules) Order(room Room, review bool) []string {
	names := r.executors
	if review {
		names = r.reviewers
	}
	var order []string
	for _, name := range names {
		if !room.Spent(name) {
			order = append(order, name)
		}
	}
	type key struct {
		credits, unknown bool
		budget           float64
	}
	keys := map[string]key{}
	for _, name := range order {
		budget, known := room.Budget(name)
		keys[name] = key{room.OnCredits(name), !known, budget}
	}
	slices.SortStableFunc(order, func(a, b string) int {
		x, y := keys[a], keys[b]
		switch {
		case x.credits != y.credits:
			return compare(x.credits)
		case x.unknown != y.unknown:
			return compare(x.unknown)
		case x.budget > y.budget:
			return -1
		case x.budget < y.budget:
			return 1
		}
		return 0
	})
	return order
}

// Pair is the executor and reviewer a run takes, Python's staffing.pick_models with neither named:
// of every executor and reviewer with room, the pair of the best tier, then the earlier executor,
// then the earlier reviewer; false where none forms.
func (r *Rules) Pair(room Room) (executor, reviewer string, ok bool) {
	best, reviewers := 3, r.Order(room, true) // 3: past every tier
	// pairs come executor by executor, so the first of the best tier is the one taken
	for _, each := range r.Order(room, false) {
		for _, other := range reviewers {
			if tier := r.tier(each, other); tier < best {
				executor, reviewer, best = each, other, tier
			}
		}
	}
	return executor, reviewer, best < 3
}

// Same is whether two names are one model: the same name, or one model id on one provider.
func (r *Rules) Same(first, second string) bool {
	one, two := r.models[first], r.models[second]
	return first == second || one.Provider == two.Provider && one.ID == two.ID
}

// tier is a pair's place in the owner's order of 21 Oct 2026: 0 a reviewer on another provider,
// 1 another model on the executor's, 2 the executor's own model.
func (r *Rules) tier(executor, reviewer string) int {
	switch {
	case r.Same(executor, reviewer):
		return 2
	case r.models[executor].Provider == r.models[reviewer].Provider:
		return 1
	}
	return 0
}

// compare sorts true after false.
func compare(later bool) int {
	if later {
		return 1
	}
	return -1
}

// ranked is whether state/matrix.json may hold a lineup Python's matrix.rank places a model by:
// anything but no file, or one whose matrix lists no lineup.
func ranked() bool {
	data, err := os.ReadFile(filepath.Join(config.Home(), "state", "matrix.json"))
	if os.IsNotExist(err) {
		return false
	}
	value, _ := run.Decode(data)
	held, ok := value.(*run.Object)
	if !ok {
		return true
	}
	matrix, isObject := held.Get("matrix").(*run.Object)
	return held.Truthy("matrix") && (!isObject || matrix.Truthy("lineup"))
}
