package config

import (
	"errors"
	"os"
	"time"
)

// BackUp copies a file of the owner's to `<file>.bak-<today>` beside it, its mode and time
// kept, as install.sh's shutil.copy2 does before it changes one; it is the copy's path.
func BackUp(path string) (string, error) {
	info, err := os.Stat(path)
	if err != nil {
		return "", err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	backup := path + ".bak-" + time.Now().Format("20060102")
	if err := os.WriteFile(backup, data, info.Mode().Perm()); err != nil {
		return "", err
	}
	return backup, errors.Join(os.Chmod(backup, info.Mode().Perm()), os.Chtimes(backup, time.Time{}, info.ModTime()))
}
