package seat

import (
	"errors"
	"io/fs"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

// A record naming no pid proves nothing alive: what is alive beside it leaves the stop to Python,
// which ends it, before anything moves.
func TestStopLeavesLiveWorkToPython(t *testing.T) {
	for name, build := range map[string]func(t *testing.T, dir string){
		"a user manager that may hold its unit": func(t *testing.T, _ string) {
			runtime, err := os.MkdirTemp("", "ak") // short: a socket's path has a limit
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { os.RemoveAll(runtime) })
			if err := os.Mkdir(filepath.Join(runtime, "systemd"), 0o700); err != nil {
				t.Fatal(err)
			}
			manager, err := net.Listen("unix", filepath.Join(runtime, "systemd", "private"))
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { manager.Close() })
			t.Setenv("XDG_RUNTIME_DIR", runtime)
			bin := t.TempDir()
			if err := os.WriteFile(filepath.Join(bin, "systemd-run"), nil, 0o700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
		},
		"a process carrying its marker": func(t *testing.T, dir string) {
			held := exec.Command("sleep", "600")
			held.Env = append(os.Environ(), "AGENTKIT_RUN="+dir)
			if err := held.Start(); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { held.Process.Kill(); held.Wait() })
		},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			going := runRecord(t, home, "r-going", map[string]any{"state": "running"})
			before := contents(t, going)
			build(t, filepath.Dir(going))
			if _, known, err := Stop("acme", moment); known || err != nil {
				t.Fatalf("Go stopped it: known=%v err=%v", known, err)
			}
			if _, err := os.Stat(filepath.Join(home, ".agentkit", "state", "seat-acme.json")); !errors.Is(err, fs.ErrNotExist) || contents(t, going) != before {
				t.Fatalf("something moved: %v %s", err, contents(t, going))
			}
		})
	}
}
