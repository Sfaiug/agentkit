package seat

import (
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// Carried is whether Go opens a new seat of that name on that model, or with preview prints the
// line it would open on, settled before its usage is read or anything written, as every case Go
// leaves to Python must be: the config bound as Python binds it, [defaults]' efforts not standing
// in for the model's own; its harness's seats Go's to open on each login its provider lists; and,
// for an open, no file of a gone seat left under the name.  Past it, whatever fails is an error.
func Carried(name string, model config.Model, preview bool) bool {
	if _, err := config.Bind(); err != nil {
		return false
	}
	listed, err := config.Accounts(model.Provider)
	named := slices.ContainsFunc(listed, func(account string) bool { return account != config.DefaultAccount })
	if err != nil || named && harness.UsualLoginOnly(model.Harness) {
		return false
	}
	if preview {
		return true
	}
	_, known := harness.Opens(model.Harness)
	_, err = config.Models()
	return known && err == nil && unclaimed(filepath.Join(config.Home(), "state"), name)
}
