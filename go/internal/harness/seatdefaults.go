package harness

import (
	"slices"

	"agentkit/internal/config"
)

// An adapter without a plugin uses Python's default hooks: its record owns the
// launcher's conversation, and its manifest decides what the screen says.
func seatDefaults(name string) plugin {
	if own, named := plugins[name]; named || name == "" {
		return own
	}
	names, err := config.ManifestNames()
	known := err == nil && slices.Contains(names, name)
	return plugin{seats: known, looks: known}
}
