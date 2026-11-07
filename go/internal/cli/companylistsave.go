package cli

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/seat"
)

// turned is Space on the company list: of a company's listed `models`, the one at `column`, or on
// its name, 0, all of them, turned on where any is off, else off, saved at once with `yours`
// (modelsListed).
func turned(models [][2]string, column int, yours []string) (string, bool) {
	_, off, err := config.ModelList()
	if err != nil {
		return "", false
	}
	if column > 0 {
		models = models[column-1 : column]
	}
	some := slices.ContainsFunc(models, func(model [2]string) bool { return slices.Contains(off, model[0]) })
	for _, model := range models {
		if off = slices.DeleteFunc(off, func(slug string) bool { return slug == model[0] }); !some {
			off = append(off, model[0])
		}
	}
	return modelsListed(yours, off)
}

// dropped is Esc on the company list: each of yours the lineup's `rows` name with no listed model
// on leaves `companies`, and every release those rows give it, one without a score too, leaves
// `models_off`, saved at once (modelsListed); where none goes nothing is written.
func dropped(rows []quality.Row, view menu.CompanyListView) (string, bool) {
	_, off, err := config.ModelList()
	if err != nil {
		return "", false
	}
	on := func(maker string) bool {
		at := slices.IndexFunc(view.Listed, func(one matrix.Company) bool { return one.Maker == maker })
		return at >= 0 && slices.ContainsFunc(view.Listed[at].Models, func(model [2]string) bool { return !slices.Contains(off, model[0]) })
	}
	gone, releases := map[string]bool{}, map[string]bool{}
	for _, row := range rows {
		if slices.Contains(view.Yours, row.Maker) && !on(row.Maker) {
			gone[row.Maker], releases[row.Release] = true, true
		}
	}
	if len(gone) == 0 {
		return "", true
	}
	return modelsListed(slices.DeleteFunc(slices.Clone(view.Yours), func(maker string) bool { return gone[maker] }),
		slices.DeleteFunc(off, func(slug string) bool { return releases[slug] }))
}

// modelsListed is Python's menu.models_listed: `yours` saved as `companies` and `off` as
// `models_off` (config.SaveModelList), every seat's record first holding the efforts it runs at
// (seat.SaveWhole).  What to say, why it was not saved, as Python's menu._saved says it, or "";
// false, with nothing written, leaves the change to Python.
func modelsListed(yours, off []string) (string, bool) {
	carried, err := seat.SaveWhole(func(keep func() error) error { return config.SaveModelList(yours, off, keep) })
	if carried && err != nil {
		return "config: " + config.PyError(err), true
	}
	return "", carried
}
