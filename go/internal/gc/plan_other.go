//go:build !linux

package gc

import (
	"errors"
	"io/fs"
	"os"
)

// ported: elsewhere the plan is Python's.
const ported = false

func open(string, bool) (*os.File, error)          { return nil, errors.ErrUnsupported }
func statOf(fs.FileInfo) (stat, bool)              { return stat{}, false }
func unlocked(*os.File) bool                       { return false }
func diskUse(string) (used, total uint64, ok bool) { return 0, 0, false }
