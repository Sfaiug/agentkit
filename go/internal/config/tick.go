package config

import (
	"errors"
	"io/fs"
	"os"
)

// Listable is whether dir's entries can be read, nothing there holding none: Glob passes over a
// folder it cannot read, which says nothing of what the folder holds.
func Listable(dir string) bool {
	_, err := os.ReadDir(dir)
	return err == nil || errors.Is(err, fs.ErrNotExist)
}
