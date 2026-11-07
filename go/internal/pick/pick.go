// Package pick holds the rules that choose a run's models from what a usage read says of them,
// Python's usage.pick_order and the staffing rules review_pair calls: the models with room for a
// role, ranked by the budget they have left, and the pair a run takes, a reviewer on another
// provider first, then another model, then the executor's own.  It never reads a meter: a read
// answers it through Room.
package pick

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Room is what a pick asks a usage read of each model.
type Room interface {
	// Spent is why nothing is picked on it: a meter gating it spent, or its provider parked; ""
	// where something may be.
	Spent(model string) string
	// Budget is its budget, and why its reading cannot tell, "" where it can.
	Budget(model string) (float64, string)
	// OnCredits is whether it runs on credits past a spent window.
	OnCredits(model string) bool
	// Pace is how far the meters gating it run ahead of their windows at most, false where none
	// reports a pace.
	Pace(model string) (float64, bool)
}

// Rules are a run's groups, as its picks read them.
type Rules struct {
	executors, reviewers []string
	reviewList           []string // reviewers as the group names them, those barred from reviewing too
	models               map[string]config.Model
	payg                 map[string]bool // paying's
	margin               float64         // pace_margin, how far ahead of pace lets a payg model in
}

// Load is the Rules of the home's groups as they stand: in a seat the seat's own, as a launch from
// it binds them (config.BindSeat), which Python's role_groups reads for whatever bound none.
func Load() (*Rules, bool) {
	executors, reviewers, err := config.Groups()
	_, seat, unread := config.CurrentSession()
	if seat != nil {
		bound, unbound := config.BindSeat(seat)
		executors, reviewers, err = nil, nil, unbound
		for _, name := range bound.Workers {
			executors = append(executors, name.(string))
		}
		for _, name := range bound.Reviewers {
			reviewers = append(reviewers, name.(string))
		}
	}
	if err != nil || unread != nil {
		return nil, false
	}
	return Within(executors, reviewers)
}

// Within is the Rules of these groups, reviewers nil being the executors, false where Python ak
// picks there: a pace_margin Python refuses, a model a group names that config.model refuses, a
// matrix lineup from state/matrix.json that ranks the models, are not yet Go's.
func Within(executors, reviewers []string) (*Rules, bool) {
	margin, ok := config.PaceMargin()
	models, err := config.Models()
	subs, failed := config.Subscriptions()
	if !ok || err != nil || failed != nil || ranked(models) {
		return nil, false
	}
	if reviewers == nil {
		reviewers = executors
	}
	for _, name := range append(slices.Clone(executors), reviewers...) {
		if _, ok := models[name]; !ok {
			return nil, false
		}
	}
	rules := &Rules{executors: executors, models: models, reviewList: reviewers, payg: paying(models, subs), margin: margin}
	for _, name := range reviewers {
		allowed, err := config.CanReview(models[name].Harness)
		if err != nil {
			return nil, false
		}
		if allowed {
			rules.reviewers = append(rules.reviewers, name)
		}
	}
	return rules, true
}

// Order is the models with room for a role, executors or with review reviewers, Python's
// usage.pick_order: a payg one only once no subscription one is below pace (paid), one on credits
// after every one with a window left, an unknown budget after every known one, then the most
// budget first, else the order config.toml lists them in.  told, unless nil, hears each model
// left out and why, then each whose budget is unknown.
func (r *Rules) Order(room Room, review bool, told io.Writer) []string {
	names, role := r.executors, "executor"
	if review {
		names, role = r.reviewers, "reviewer"
	}
	var order []string
	for _, name := range names {
		if why := room.Spent(name); why == "" {
			order = append(order, name)
		} else if told != nil {
			fmt.Fprintf(told, "pick %s: %s excluded: %s\n", role, name, why)
		}
	}
	order = r.paid(room, order)
	type key struct {
		credits, unknown bool
		budget           float64
	}
	keys := map[string]key{}
	for _, name := range order {
		budget, why := room.Budget(name)
		keys[name] = key{room.OnCredits(name), why != "", budget}
		if why != "" && told != nil {
			fmt.Fprintf(told, "pick %s: %s (%s) budget %s unknown: %s; after every known budget of its rank\n", role, name,
				r.models[name].Provider, strconv.FormatFloat(budget, 'g', 6, 64), strings.TrimPrefix(why, "unknown: "))
		}
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
	return r.pair(room, r.Order(room, false, nil))
}

// PairFor is the reviewer a run whose executor was named takes, Python's staffing.pick_models
// with --exec: the named executor's meter is never read; false where none forms.
func (r *Rules) PairFor(room Room, executor string) (reviewer string, ok bool) {
	_, reviewer, ok = r.pair(room, []string{executor})
	return reviewer, ok
}

// pair is the pair of the best tier of these executors, in their order, and every reviewer with
// room, Python's best_pair.
func (r *Rules) pair(room Room, executors []string) (executor, reviewer string, ok bool) {
	best, reviewers := 3, r.Order(room, true, nil) // 3: past every tier
	// pairs come executor by executor, so the first of the best tier is the one taken
	for _, each := range executors {
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
	return r.tier(first, second) == 2
}

func (r *Rules) tier(executor, reviewer string) int {
	return Tier(r.models, executor, reviewer)
}

// Tier is a pair's place in the owner's order of 21 Oct 2026, of models as config.Models has them:
// 0 a reviewer on another provider, 1 another model on the executor's, 2 the executor's own model.
func Tier(models map[string]config.Model, executor, reviewer string) int {
	one, two := models[executor], models[reviewer]
	switch {
	case executor == reviewer || one.Provider == two.Provider && one.ID == two.ID:
		return 2
	case one.Provider == two.Provider:
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

// ranked is whether state/matrix.json may hold a lineup Python's matrix.rank places one of models
// by: anything but no file, a matrix listing no lineup, or a lineup no row of which a model's
// harness runs as that model (`yours`).  A model no row is ranks after every ranked one, so where
// none is, budget alone orders them, as here.
func ranked(models map[string]config.Model) bool {
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
	if !held.Truthy("matrix") || isObject && !matrix.Truthy("lineup") {
		return false
	}
	if !isObject {
		return true
	}
	lineup, listed := matrix.Get("lineup").([]any)
	if !listed {
		return true
	}
	for _, row := range lineup {
		entry, ok := row.(*run.Object)
		if !ok {
			return true
		}
		yours, listed := entry.Get("yours").([]any)
		if !listed {
			return true
		}
		for _, one := range yours {
			own, ok := one.(*run.Object)
			if !ok {
				return true
			}
			for _, model := range models {
				if own.Get("harness") == model.Harness && own.Get("model") == model.ID {
					return true
				}
			}
		}
	}
	return false
}
