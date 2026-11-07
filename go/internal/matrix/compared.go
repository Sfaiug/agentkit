package matrix

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/quality"
)

// Compared is the releases on, the only ones `ak models` and its screen compare, and how many
// releases are ours, as Python's matrix.compared and matrix.ours read rows, the lineup stored.  A
// release is listed where a role rates a row of it, so one without scores never is; ours where
// its maker is one of your companies: `companies` in the config, else the makers of what the
// [defaults] models run; on where ours and not in `models_off`, so a company's next release is
// on by itself.  Only these are compared: the owner, 5 Nov 2026.
func Compared(rows []quality.Row) (map[string]bool, int, error) {
	companies, off, err := config.ModelList()
	if err != nil {
		return nil, 0, err
	}
	if companies == nil {
		defaults, err := config.Defaults()
		if err != nil {
			return nil, 0, err
		}
		models, err := config.Models()
		if err != nil {
			return nil, 0, err
		}
		runs := map[[2]string]bool{}
		for _, name := range append(append([]string{defaults.Orchestrator}, defaults.Workers...), defaults.Reviewers...) {
			if model, configured := models[name]; configured {
				runs[[2]string{model.Harness, model.ID}] = true
			}
		}
		companies = []string{}
		for _, row := range rows {
			if slices.ContainsFunc(row.Runners, func(runner [2]string) bool { return runs[runner] }) {
				companies = append(companies, row.Maker)
			}
		}
	}
	ours := map[string]bool{}
	for _, role := range quality.Roles {
		for _, row := range quality.Rated(rows, role) {
			if slices.Contains(companies, row.Maker) {
				ours[row.Release] = true
			}
		}
	}
	on := map[string]bool{} // never nil: with none on, none is compared
	for release := range ours {
		if !slices.Contains(off, release) {
			on[release] = true
		}
	}
	return on, len(ours), nil
}
