//go:build !unix

package notify

import "io/fs"

// single is whether a card is a plain file: off Unix no owner or link count is read.
func single(info fs.FileInfo) bool { return info.Mode().IsRegular() }
