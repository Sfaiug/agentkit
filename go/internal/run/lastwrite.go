package run

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// LastWrite is the newest write under dir (watch.run_last_write): the run's last sign of life.
// Locks and temp files are the tick's own bookkeeping, not the run's life.
func LastWrite(dir string) float64 {
	// os.walk enters its starting directory through a link, as WalkDir does not
	root, err := filepath.EvalSymlinks(dir)
	if err != nil {
		return 0
	}
	var latest float64
	filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() || strings.HasSuffix(path, ".lock") || strings.HasSuffix(path, ".tmp") {
			return nil
		}
		// a link to a directory is one os.walk lists and never enters
		if info, err := os.Stat(path); err == nil && !info.IsDir() {
			latest = max(latest, seconds(info.ModTime()))
		}
		return nil
	})
	return latest
}
