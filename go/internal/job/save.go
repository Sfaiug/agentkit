package job

import (
	"errors"
	"os"
	"path/filepath"

	"agentkit/internal/run"
)

// ErrStopped is a save a stop landed before: the receipt it would write over says the job finished.
var ErrStopped = errors.New("stopped")

// Save writes the receipt of the job at dir as Python's save_job does, under its recovery lock,
// unless a stop landed first: a finished receipt is never written back to unfinished.
func Save(dir string, record *run.Object) error {
	release, err := run.Hold(dir)
	if err != nil {
		return err
	}
	defer release()
	if current, _ := Read(dir); !record.Truthy("finished_at") && current != nil && current.Truthy("finished_at") {
		return ErrStopped
	}
	tmp := filepath.Join(dir, "job.tmp")
	if err := os.WriteFile(tmp, []byte(run.EncodeText(record)), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, receipt(dir))
}
