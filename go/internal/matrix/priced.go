package matrix

import (
	"errors"

	"agentkit/internal/boards"
	"agentkit/internal/config"
	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// ErrPriced is a lineup Priced holds for: its answer is Python's.
var ErrPriced = errors.New("a measured task share prices the lineup")

// unpriced refuses boards, as asked and before anything is written, whose lineup Priced holds for.
func unpriced(held *run.Object) error {
	// pricing reads the rows' releases and efforts alone, so no harness catalog is asked
	priced, err := Priced(rowsOf(lineup(held, nil, nil)))
	if err == nil && priced {
		err = ErrPriced
	}
	return err
}

// Priced is whether Python's answer over rows prices one by the share of a week a task takes
// (usage.TaskUsage), as matrix._costs does once an offered model found as that row's release
// alone has a share measured at the row's effort: every row's cost, and so each role's pick, then
// follows the measured shares.  Go's answer prices from the boards alone, so where this holds the
// answer is Python's.
func Priced(rows []quality.Row) (bool, error) {
	readings, err := usage.Cached()
	if err != nil {
		return false, err
	}
	rates, err := readings.Rates()
	if err != nil {
		return false, err
	}
	shares := usage.TaskUsage(rates)
	names, err := config.Offered()
	if err != nil {
		return false, err
	}
	models, err := config.Models()
	if err != nil {
		return false, err
	}
	var releases []*boards.Release
	named := map[string]*boards.Release{}
	for _, row := range rows {
		if named[row.Release] == nil {
			named[row.Release] = &boards.Release{Slug: row.Release}
			releases = append(releases, named[row.Release])
		}
		named[row.Release].Name = row.Name // the last row's, as Python's dict of them keeps it
	}
	index := indexOf(releases)
	for _, name := range names {
		slugs := map[string]bool{}
		for _, one := range found(index, models[name].ID) {
			slugs[one.release.Slug] = true
		}
		efforts := shares.Dict(name)
		if len(slugs) != 1 || efforts == nil {
			continue
		}
		for _, row := range rows {
			if roles := efforts.Dict(row.Effort); slugs[row.Release] && roles != nil {
				for _, role := range roles.Keys() {
					if roles.Get(role) != nil {
						return true, nil
					}
				}
			}
		}
	}
	return false, nil
}
