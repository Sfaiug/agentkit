package matrix

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/quality"
)

// A Company is a maker with a listed release, and its listed releases, each its slug and name.
type Company struct {
	Maker  string
	Models [][2]string
}

// Companies is each company with a listed release, in the order of the lineup rows, each with
// its listed models in that order, as Python's menu.companies_listed reads them; and yours.
func Companies(rows []quality.Row) ([]Company, []string, error) {
	companies, _, err := config.ModelList()
	if err != nil {
		return nil, nil, err
	}
	if companies, err = yours(rows, companies); err != nil {
		return nil, nil, err
	}
	found := rated(rows)
	var makers []Company
	for _, row := range rows {
		if _, ok := found[row.Release]; !ok {
			continue
		}
		at := slices.IndexFunc(makers, func(one Company) bool { return one.Maker == row.Maker })
		if at < 0 {
			at, makers = len(makers), append(makers, Company{Maker: row.Maker})
		}
		model := [2]string{row.Release, row.Name} // a row per effort, each named as its release
		if !slices.Contains(makers[at].Models, model) {
			makers[at].Models = append(makers[at].Models, model)
		}
	}
	return makers, companies, nil
}

// rated is each release listed, one a role rates a row of, by its maker: one without scores never is.
func rated(rows []quality.Row) map[string]string {
	found := map[string]string{}
	for _, role := range quality.Roles {
		for _, row := range quality.Rated(rows, role) {
			found[row.Release] = row.Maker
		}
	}
	return found
}

// yours is your companies: `companies` as the config lists them, else the makers of what the
// [defaults] models run, in the order the lineup rows first name them.
func yours(rows []quality.Row, companies []string) ([]string, error) {
	if companies != nil {
		return companies, nil
	}
	defaults, err := config.Defaults()
	if err != nil {
		return nil, err
	}
	models, err := config.Models()
	if err != nil {
		return nil, err
	}
	runs := map[[2]string]bool{}
	for _, name := range append(append([]string{defaults.Orchestrator}, defaults.Workers...), defaults.Reviewers...) {
		if model, configured := models[name]; configured {
			runs[[2]string{model.Harness, model.ID}] = true
		}
	}
	had := map[string]bool{}
	for _, row := range rows {
		if slices.ContainsFunc(row.Runners, func(runner [2]string) bool { return runs[runner] }) {
			had[row.Maker] = true
		}
	}
	companies = []string{}
	for _, row := range rows {
		if had[row.Maker] && !slices.Contains(companies, row.Maker) {
			companies = append(companies, row.Maker)
		}
	}
	return companies, nil
}
