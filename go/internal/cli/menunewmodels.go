package cli

import (
	"context"

	modelListing "agentkit/internal/listing"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// draftModels opens a new seat's models screen once its harnesses' catalogs are read.
func draftModels(d *menu.Draft, cells []menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	return draftLevels(d, configCatalog{ask: func(harness string) ([]modelListing.Choice, error) {
		return waitConfigCatalog(harness, "new session", cells, keyboard, painter)
	}})
}

// draftLevels gives the draft's models the efforts their catalogs list, each harness read once
// per visit as c reads them, so a step lands only on an effort its model runs at. Esc while
// they are read keeps the row; false hands over.
func draftLevels(d *menu.Draft, catalogs configCatalog) bool {
	err := catalogs.read(&matrix.Configuration{Names: d.Names, Models: d.Models, Levels: d.Levels})
	d.Picker = err == nil
	return err == nil || err == context.Canceled
}
