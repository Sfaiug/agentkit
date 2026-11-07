package seat

import (
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// Carried is whether Go opens a new seat of that name on that model, or with preview prints the
// line it would open on, settled before its usage is read or anything written, as every case Go
// leaves to Python must be: the config bound as Python binds it, [defaults]' efforts not standing
// in for the model's own; and, for an open, no file of a gone seat left under the name.  Past it,
// whatever fails is an error.
func Carried(name string, model config.Model, preview bool) bool {
	if _, err := config.Bind(); err != nil {
		return false
	}
	if preview {
		return true
	}
	_, known := harness.Opens(model.Harness)
	_, err := config.Models()
	return known && err == nil && unclaimed(filepath.Join(config.Home(), "state"), name)
}
