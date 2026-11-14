//go:build linux

package loop

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A tick's launch Go would not drive to its end is Python's, its task file and receipt unwritten,
// so no error run claims what Python's tick then launches.
func TestATickLaunchGoDoesNotDriveWritesNothing(t *testing.T) {
	rig(t, 0)
	seatLaunchFixture(t)
	t.Setenv("AK_MAX_RUNS", "0")
	previous := Drivable
	Drivable = func(config.Binding, config.Numbers) error { return errors.New("several logins") }
	t.Cleanup(func() { Drivable = previous })
	before, _ := os.ReadDir(run.Runs())
	path := filepath.Join(os.Getenv("HOME"), ".agentkit", "tasks", "acme", "night-review.md")
	_, err := LaunchForSeat("acme", "night-review", path, "# Review\n", run.Fields("repo", os.Getenv("HOME")))
	after, _ := os.ReadDir(run.Runs())
	if _, missing := os.Stat(path); !errors.Is(err, ErrLeft) || !os.IsNotExist(missing) || len(after) != len(before) {
		t.Fatalf("err=%v task written=%v runs %d -> %d", err, missing == nil, len(before), len(after))
	}
}
