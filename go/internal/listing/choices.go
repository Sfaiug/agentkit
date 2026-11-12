package listing

import (
	"context"
	"slices"
	"strings"

	"agentkit/internal/config"
)

// Choice keeps the adapter's label beside the efforts used by both the matrix and Models.
type Choice struct {
	ID, Label string
	Efforts   []string
}

func Choices(harness string) ([]Choice, error) {
	return ChoicesContext(context.Background(), harness)
}

func choices(harness string, rows [][]string) ([]Choice, error) {
	if len(rows) == 0 {
		var err error
		if rows, err = config.CatalogTable(harness); err != nil {
			return nil, err
		}
	}
	var choices []Choice
	for _, row := range rows {
		if slices.ContainsFunc(choices, func(one Choice) bool { return one.ID == row[0] }) {
			continue
		}
		said := ""
		if len(row) > 2 {
			said = row[2]
		}
		label := config.ModelLabel(harness, row[0], said)
		levels := strings.FieldsFunc(row[1], config.Space)
		if len(levels) == 0 {
			var err error
			if levels, err = config.Efforts(harness, row[0]); err != nil {
				return nil, err
			}
		}
		choices = append(choices, Choice{row[0], label, levels})
	}
	return choices, nil
}
