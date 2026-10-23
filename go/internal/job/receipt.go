package job

import (
	"path/filepath"

	"agentkit/internal/config"
)

func ReceiptPath(id string) string {
	return filepath.Join(config.Home(), "jobs", id, "job.json")
}
