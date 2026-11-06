package cli

import (
	"cmp"
	"context"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// ticksNote is what `Models` says under its rows.
const ticksNote = "Space on a model under its harness takes it in or out of the config."

// menuConfigModels is `Models` on `c` (menu.models_page): a row per harness the config's providers
// run on, in its colour, opening every model it lists (modelsList), ■ each the config runs there,
// Space taking it in or out (config.ModelTicks), saved at once; on a host, the config's providers
// it has no login for after them, Enter logging in to one.
func menuConfigModels(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	ticks, err := config.OpenModelTicks()
	if err != nil || len(ticks.Harnesses) == 0 {
		return false
	}
	catalogs := map[string][]throughChoice{} // each harness's, once read this visit
	return configPage("models", ticksNote, func() ([]menu.PageRow, bool) {
		models, err := config.Models()
		if err != nil {
			return nil, false
		}
		var rows []menu.PageRow
		for _, harness := range ticks.Harnesses {
			name, colour := config.HarnessLook(harness)
			labels := []string{}
			for _, name := range ticks.Names(harness, "") {
				labels = append(labels, config.ModelName(name, models))
			}
			rows = append(rows, menu.PageRow{Label: name, Colour: colour, Value: cmp.Or(strings.Join(labels, ", "), "none"), Several: true,
				List: func() ([]menu.PageRow, bool) { return modelChoices(harness, ticks, catalogs, keyboard, painter) }})
		}
		return rows, true
	}, keyboard, painter)
}

// modelChoices is the list a harness's row opens: each choice modelsList makes, asked behind the
// waiting rule until one answer is read, ■ each model the config runs, and a provider logged in to
// asking it again, its models listed now; else a line saying why none is.
func modelChoices(harness string, ticks *config.ModelTicks, catalogs map[string][]throughChoice, keyboard *terminal.Keyboard, painter *terminal.Painter) ([]menu.PageRow, bool) {
	if _, read := catalogs[harness]; !read {
		choices, err := modelsList(harness, keyboard, painter)
		switch {
		case err == context.Canceled:
			return []menu.PageRow{{Value: "not read: esc and open it again"}}, true
		case err != nil:
			return []menu.PageRow{{Value: err.Error()}}, true
		}
		catalogs[harness] = choices
	}
	if len(catalogs[harness]) == 0 {
		return []menu.PageRow{{Value: "its catalog lists no model"}}, true
	}
	var choices []menu.PageRow
	for _, chosen := range catalogs[harness] {
		if model := chosen.model; model != nil {
			choices = append(choices, menu.PageRow{Value: model.Label, On: len(ticks.Names(harness, model.ID)) > 0, Flip: func() string {
				if err := ticks.Tick(harness, model.ID, model.Label, model.Efforts, chosen.under(), seat.KeepConfigEfforts); err != nil {
					return err.Error()
				}
				return ""
			}})
			continue
		}
		provider := chosen.provider
		choices = append(choices, menu.PageRow{Value: provider.Name, Does: "log in", Act: func() string {
			verb := adapterVerbs(keyboard, painter, harness, []string{"login"}, "", provider.ID, false)
			painter.Forget()
			if verb != "" {
				return notAdded(harness, verb, provider.Name)
			}
			delete(catalogs, harness)
			return ""
		}})
	}
	return choices, true
}
