package harness

import (
	"cmp"
	"regexp"

	"agentkit/internal/config"
)

// bracketed is the effort agy 1.5 brackets after a model's own label.
var bracketed = regexp.MustCompile(` \([^()]*\)$`)

// antigravityReported is the model agy's status line reports, which it names by its own label,
// its effort bracketed after it, even as `model.id`: the id of the row named as that label is
// (config.ModelLabel), off its own label or its id; the label itself where no row is
// (antigravity.py `running`).
func antigravityReported(model string) (string, error) {
	label := bracketed.ReplaceAllString(model, "")
	named := config.ModelLabel("antigravity", "", label)
	rows, err := config.CatalogTable("antigravity")
	catalog, _ := config.Tree("antigravity", "catalog")
	for _, row := range rows {
		entry, _ := catalog[row[0]].(map[string]any)
		if own, _ := entry["label"].(string); config.ModelLabel("antigravity", "", cmp.Or(own, row[0])) == named {
			return row[0], err
		}
	}
	return label, err
}
