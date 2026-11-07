//go:build linux

package suitetimes

import (
	"os"
	"path/filepath"
	"testing"
)

// A test path's `..` after a link climbs from where the link leads, as Python's Path.is_file.
func TestHasFollowsLinkBeforeDotDot(t *testing.T) {
	checkout := t.TempDir()
	if err := os.MkdirAll(filepath.Join(checkout, "real", "sub"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(checkout, "real", "a.py"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(checkout, "real", "sub"), filepath.Join(checkout, "link")); err != nil {
		t.Fatal(err)
	}
	if !has(checkout, "link/../a.py::part") {
		t.Fatal("link/../a.py is real/a.py, a file the checkout has")
	}
	if has(checkout, "real/../a.py") {
		t.Fatal("real/../a.py is a.py, a file the checkout lacks")
	}
}
