package pick

import (
	"cmp"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// paying is the models paid as they go, Python's pick_order `mode`: what the harness's own config
// says of how a model is paid outranks the model's own `mode`, which outranks its provider's.
func paying(models map[string]config.Model, subs []config.Subscription) map[string]bool {
	provider := map[string]string{}
	for _, sub := range subs {
		provider[sub.Name] = sub.Mode
	}
	payg := map[string]bool{}
	for name, model := range models {
		payg[name] = cmp.Or(harness.Mode(model), model.Mode, provider[model.Provider]) == "payg"
	}
	return payg
}

// paid is those models less every payg one while any subscription model among them is still
// below pace, Python's pick_order: payg costs money.  A subscription model whose meters report
// no pace counts as below it.
func (r *Rules) paid(room Room, names []string) []string {
	subs := slices.DeleteFunc(slices.Clone(names), func(name string) bool { return r.payg[name] })
	if slices.ContainsFunc(subs, func(name string) bool {
		pace, known := room.Pace(name)
		return !known || pace <= r.margin
	}) {
		return subs
	}
	return names
}
