package harness

import (
	"cmp"
	"regexp"

	"agentkit/internal/config"
)

// bracketed is the effort agy 1.5 brackets after a model's catalog label.
var bracketed = regexp.MustCompile(` \([^()]*\)$`)

// antigravityReported is the model agy's status line reports, which it names by its catalog
// label, its effort bracketed after it, even as `model.id`: that row's id, the label itself where
// no row has it (antigravity.py `running`).
func antigravityReported(model string) (string, error) {
	label := bracketed.ReplaceAllString(model, "")
	rows, err := config.CatalogTable("antigravity")
	catalog, _ := config.Tree("antigravity", "catalog")
	for _, row := range rows {
		entry, _ := catalog[row[0]].(map[string]any)
		if named, _ := entry["label"].(string); cmp.Or(named, row[0]) == label {
			return row[0], err
		}
	}
	return label, err
}
