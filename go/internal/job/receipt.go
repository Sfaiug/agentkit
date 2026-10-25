package job

import (
	"path/filepath"

	"agentkit/internal/config"
)

// Jobs is where every job keeps its directory.
func Jobs() string {
	return filepath.Join(config.Home(), "jobs")
}

func ReceiptPath(id string) string {
	return filepath.Join(Jobs(), id, "job.json")
}
