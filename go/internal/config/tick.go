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

// MayRent is whether `[google_cloud]` lets ak rent machines, or is not one Go can read.
func MayRent() bool {
	value, _, err := topLevel("google_cloud")
	if err != nil {
		return true
	}
	if value == nil {
		return false
	}
	rented, ok := value.(*table)
	return !ok || rented.values["active"] == true
}
