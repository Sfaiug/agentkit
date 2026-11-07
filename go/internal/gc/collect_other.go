//go:build !linux

package gc

import "io/fs"

// Elsewhere the collection is Python's, as its plan is.

func diskBytes(fs.FileInfo) int64 { return 0 }
func shut(string) bool            { return true }
func clearUnits(func(string))     {}
