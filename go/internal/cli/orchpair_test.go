//go:build unix

package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// A home path is opened as given: `link/..` is where the link leads's parent, as the filesystem
// and Python's Path read it, never the home beside the link that cleaning the path would name.
func TestAHomePathThroughALinkIsTheHomeItLeadsTo(t *testing.T) {
	root := t.TempDir()
	t.Setenv("HOME", root)
	write(t, filepath.Join(root, "actual", "home", "connection.json"), `{"socket": "`+filepath.Join(root, "gone")+`"}`)
	if err := os.MkdirAll(filepath.Join(root, "actual", "nested"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, "visible"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(root, "actual", "nested"), filepath.Join(root, "visible", "link")); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	code := orchPair([]string{filepath.Join(root, "visible", "link") + "/../home"}, &out, &errOut)
	// the socket the intended home names is gone; visible/home has no connection.json at all
	if code != 1 || out.Len() != 0 || errOut.String() != "codex seat: [Errno 2] No such file or directory\n" {
		t.Fatalf("exit=%d stdout=%q stderr=%q", code, out.String(), errOut.String())
	}
}
