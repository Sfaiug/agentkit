package uncommitted

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

// goCacheReadme is how the README Go writes at a build cache's root begins (cmd/go/internal/cache).
// GOCACHE may name that directory anything, so only this tells one: a check that set it inside the
// checkout had its cache's 2153 files committed with the work, and the run refused before review.
const goCacheReadme = "This directory holds cached build artifacts from the Go build system.\n"

// goBuildCache is whether path is in a Go build cache in wt, Python's go_build_cache: below a
// directory holding the README Go writes at a cache's root, that README included, wt's own root
// among them.
func goBuildCache(wt, path string) bool {
	dir := wt
	for _, part := range strings.Split(path, "/") {
		if goCacheRoot(dir) {
			return true
		}
		dir = filepath.Join(dir, part)
	}
	return false
}

// goCacheRoot opens dir's README nonblocking: a FIFO named README would otherwise hold the run
// until a writer came.  Windows has no such file and ignores the flag.
func goCacheRoot(dir string) bool {
	readme, err := os.OpenFile(filepath.Join(dir, "README"), os.O_RDONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		return false
	}
	defer readme.Close()
	head := make([]byte, len(goCacheReadme))
	_, err = io.ReadFull(readme, head)
	return err == nil && string(head) == goCacheReadme
}
