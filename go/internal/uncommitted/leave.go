package uncommitted

import (
	"os"
	"path/filepath"

	"agentkit/internal/gitcall"
)

// leave makes the index file private writes the checkout's as the loop leaves it after its commit:
// every other staged entry kept, which Git reads where attributes are absent on disk, the junk
// unstaged, and the committable paths, real, staged.
func leave(g, private gitcall.Git, index string, real, unstage []string) error {
	source, err := g.Must("rev-parse", "--git-path", "index")
	if err != nil {
		return err
	}
	if !filepath.IsAbs(source) {
		source = filepath.Join(g.Repo, source)
	}
	if data, failed := os.ReadFile(source); failed != nil {
		_, err = private.Must("read-tree", "--empty") // a checkout with no index yet
	} else {
		err = os.WriteFile(index, data, 0o666)
	}
	if err != nil {
		return err
	}
	if len(unstage) > 0 {
		if _, err := private.Must(append([]string{"reset", "-q", "HEAD", "--"}, unstage...)...); err != nil {
			return err
		}
	}
	return Add(private, real)
}
