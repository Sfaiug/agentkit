//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A line's lander is the installed ak, ~/.local/bin/ak where that is a file, else this program.
// HOME's `..` after a link is the link's target's parent, as to Python, never the folder holding
// the link, whose own ~/.local/bin/ak is not this home's.
func TestALanderStartsTheInstalledAk(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	home := filepath.Join(root, "real")
	if err := os.MkdirAll(filepath.Join(home, "inner"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("real/inner", filepath.Join(root, "link")); err != nil {
		t.Fatal(err)
	}
	// no user manager: each starts plainly
	for key, value := range map[string]string{"HOME": root + "/link/..", "XDG_RUNTIME_DIR": t.TempDir()} {
		t.Setenv(key, value)
	}
	turn := filepath.Join(run.Runs(), ".merge-acme.lock")
	if err := os.MkdirAll(run.Runs(), 0o700); err != nil {
		t.Fatal(err)
	}
	said := filepath.Join(home, "lander")
	started := func() string {
		os.Remove(said)
		if err := land(turn, nil, append(os.Environ(), "AK_TEST_LANDER="+said)); err != nil {
			t.Fatal(err)
		}
		for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
			if data, _ := os.ReadFile(said); len(data) > 0 {
				return string(data)
			}
		}
		t.Fatal("no lander started")
		return ""
	}
	installed := filepath.Join(home, ".local", "bin", "ak")
	for _, ak := range []string{installed, filepath.Join(root, ".local", "bin", "ak")} {
		os.MkdirAll(filepath.Dir(ak), 0o700)
		os.WriteFile(ak, []byte("#!/bin/sh\nprintf %s \"$0 $*\" >\"$AK_TEST_LANDER\"\n"), 0o755)
	}
	if got, want := started(), installed+" run --lander .merge-acme.lock"; got != want {
		t.Errorf("with an installed ak, the lander was %q, want %q", got, want)
	}
	os.Remove(installed)
	self, _ := os.Executable()
	if got, want := started(), self+" run --lander .merge-acme.lock"; got != want {
		t.Errorf("with none installed, the lander was %q, want %q", got, want)
	}
}
