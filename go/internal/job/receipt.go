package job

import (
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Jobs is where every job keeps its directory.
func Jobs() string {
	return filepath.Join(config.Home(), "jobs")
}

func ReceiptPath(id string) string {
	return receipt(filepath.Join(Jobs(), id))
}

// Read is the receipt of the job at dir, as run.ReadJSON reads one.
func Read(dir string) (*run.Object, error) {
	return run.ReadJSON(receipt(dir))
}

func receipt(dir string) string { return filepath.Join(dir, "job.json") }
