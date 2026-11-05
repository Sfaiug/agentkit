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
		label := config.ModelName(row[0], map[string]config.Model{row[0]: {Harness: harness, ID: row[0]}})
		if len(row) > 2 && row[2] != "" {
			label = row[2]
		}
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
