package worker

import (
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/host"
)

// Launched is the file in a run's directory whose time is when a worker of the run last went,
// Python's worker.LAUNCHED: admission counts what a run may still grow by until its workers show.
const Launched = "launched"

// markLaunched touches Launched in the directory of the run this process drives, none where it
// drives no run, as a worker goes.
func markLaunched() {
	dir := os.Getenv(host.Marker)
	if info, err := os.Stat(dir); err != nil || !info.IsDir() {
		return
	}
	path := filepath.Join(dir, Launched)
	if file, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY, 0o666); err == nil {
		file.Close()
		now := time.Now()
		os.Chtimes(path, now, now)
	}
}
