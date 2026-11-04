package run

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
)

// Every reads the run directories afresh, in Python's record.run_dirs order, and asks read of
// each readable record. Missing or malformed records are skipped as read_state skips them;
// a directory that cannot be listed, or Python text Go cannot keep, proves nothing idle.
func Every(read func(string, *Object) bool) bool {
	entries, err := os.ReadDir(Runs())
	if err != nil {
		return errors.Is(err, fs.ErrNotExist)
	}
	for _, entry := range entries {
		dir := filepath.Join(Runs(), entry.Name())
		info, err := os.Stat(dir)
		if err != nil || !info.IsDir() {
			continue
		}
		record, err := Read(dir)
		if errors.Is(err, ErrLoneSurrogate) || errors.Is(err, ErrLimit) || record != nil && !read(dir, record) {
			return false
		}
	}
	return true
}
