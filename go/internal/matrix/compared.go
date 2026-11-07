package matrix

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/quality"
)

// Compared is the releases on, the only ones `ak models` and its screen compare, and how many
// releases are ours, as Python's matrix.compared and matrix.ours read rows, the lineup stored:
// ours, the listed releases of your companies (rated, yours); on, those of ours `models_off`
// does not hold, so a company's next release is on by itself.  Only these are compared: the
// owner, 5 Nov 2026.
func Compared(rows []quality.Row) (map[string]bool, int, error) {
	companies, off, err := config.ModelList()
	if err != nil {
		return nil, 0, err
	}
	if companies, err = yours(rows, companies); err != nil {
		return nil, 0, err
	}
	ours := map[string]bool{}
	for release, maker := range rated(rows) {
		if slices.Contains(companies, maker) {
			ours[release] = true
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
