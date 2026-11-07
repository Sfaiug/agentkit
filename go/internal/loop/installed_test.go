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
func TestALanderStartsTheInstalledAk(t *testing.T) {
	home := t.TempDir()
	// no user manager: each starts plainly
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "XDG_RUNTIME_DIR": t.TempDir()} {
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
	os.MkdirAll(filepath.Dir(installed), 0o700)
	os.WriteFile(installed, []byte("#!/bin/sh\nprintf %s \"$0 $*\" >\"$AK_TEST_LANDER\"\n"), 0o755)
	if got, want := started(), installed+" run --lander .merge-acme.lock"; got != want {
		t.Errorf("with an installed ak, the lander was %q, want %q", got, want)
	}
	os.Remove(installed)
	self, _ := os.Executable()
	if got, want := started(), self+" run --lander .merge-acme.lock"; got != want {
		t.Errorf("with none installed, the lander was %q, want %q", got, want)
	}
}
