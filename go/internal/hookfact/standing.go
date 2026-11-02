package hookfact

import (
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// Standing is the last event the seat's own harness reported (lifecycle.facts), none where it has
// reported none.
func Standing(name string) Fact {
	session, err := config.SessionPath(name)
	if err != nil {
		return Fact{}
	}
	data, err := os.ReadFile(filepath.Join(filepath.Dir(session), "hook-"+config.Fold(name)+".json"))
	if err != nil {
		return Fact{}
	}
	return read(data)
}
