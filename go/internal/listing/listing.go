// Package listing asks a harness's logins which models they run, as Python's config.catalog: an
// adapter's `models` verb answers, one `id<TAB>label<TAB>efforts` line per model, told the login.
package listing

import (
	"context"
	"slices"
	"strings"

	"agentkit/internal/config"
)

// A Model is one model a harness can run, and the efforts it takes, strongest last.
type Model struct {
	ID      string
	Efforts []string
}

// Catalog is the models that harness can run, each once, as the first login to list it says it:
// what its logins list, else its manifest's `[catalog]` table.
func Catalog(harness string) ([]Model, error) {
	rows := Ask(harness)
	if len(rows) == 0 {
		var err error
		if rows, err = config.CatalogTable(harness); err != nil {
			return nil, err
		}
	}
	var models []Model
	for _, row := range rows {
		if !slices.ContainsFunc(models, func(each Model) bool { return each.ID == row[0] }) {
			models = append(models, Model{row[0], strings.FieldsFunc(row[1], config.Space)})
		}
	}
	return models, nil
}

// Ask is each model's [id, efforts, label] the harness's logins list, asked at once, the first login's
// first.
func Ask(harness string) [][]string {
	return askContext(context.Background(), harness, "", "")
}
