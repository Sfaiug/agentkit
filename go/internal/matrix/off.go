package matrix

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/quality"
	"agentkit/internal/seat"
)

func init() { seat.ModelOff = Off }

// Off is whether ak never uses that configured model (matrix.off): one the config offers running
// a release the lineup last stored rates that is not on (Compared), so no turn or seat is had on
// it.  A model running an unlisted release, or none, is not the list's to turn off.
func Off(name string) (bool, error) {
	rows := Stored().Rows
	listed := map[string]bool{}
	for _, role := range quality.Roles {
		for _, row := range quality.Rated(rows, role) {
			listed[row.Release] = true
		}
	}
	offered, err := config.Offered()
	if err != nil || len(listed) == 0 || !slices.Contains(offered, name) {
		return false, err
	}
	on, _, err := Compared(rows)
	if err != nil {
		return false, err
	}
	model, err := config.ModelNamed(name)
	if err != nil {
		return false, err
	}
	runs := map[[2]string]string{}
	for _, row := range rows {
		for _, runner := range row.Runners {
			runs[runner] = row.Release
		}
	}
	release := runs[[2]string{model.Harness, model.ID}]
	return listed[release] && !on[release], nil
}
