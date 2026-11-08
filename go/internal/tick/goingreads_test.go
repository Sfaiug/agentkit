//go:build linux

package tick

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

func TestFrozenLoopsLeaveTheirStallClocksToPython(t *testing.T) {
	ak, _ := idleHome(t, answers)
	root := t.TempDir()
	t.Setenv("AK_CGROUP_ROOT", root)
	identity, known := host.ReadIdentity(os.Getpid())
	if !known {
		t.Fatal("test process identity unreadable")
	}
	for _, frozen := range []bool{false, true} {
		for _, saved := range []bool{false, true} {
			for _, delivery := range []bool{false, true} {
				t.Run(fmt.Sprintf("frozen=%v/saved=%v/delivery=%v", frozen, saved, delivery), func(t *testing.T) {
					value := "0\n"
					if frozen {
						value = "1\n"
					}
					put(t, filepath.Join(root, "cgroup.freeze"), value)
					record := run.Fields("state", "running", "pid", os.Getpid(), "process_identity",
						run.Fields("boot", identity.Boot, "ticks", int(identity.Ticks)))
					if saved {
						record.Set("frozen_since", 1)
					}
					if delivery {
						record.Set("delivery_wait", os.Getpid())
					}
					path := filepath.Join(ak, "runs", "r-build", "run.json")
					put(t, path, run.Line(record))
					if !run.ProcessActive(record) {
						t.Fatal("test loop not active")
					}
					if got, want := noStallRecovery(), !frozen && !saved; got != want {
						t.Fatalf("stall row idle=%v, want %v", got, want)
					}
					if read(t, path) != run.Line(record) {
						t.Fatal("Go changed the freeze bookkeeping left to Python")
					}
				})
			}
		}
	}
}

func TestALoopsFolderTheWalkCannotReadLeavesItsClockGoing(t *testing.T) {
	ak, _ := idleHome(t, answers)
	t.Setenv("AK_CGROUP_ROOT", t.TempDir())
	identity, known := host.ReadIdentity(os.Getpid())
	if !known {
		t.Fatal("test process identity unreadable")
	}
	dir := filepath.Join(ak, "runs", "r-build")
	put(t, filepath.Join(dir, "run.json"), run.Line(run.Fields("state", "running", "pid", os.Getpid(),
		"process_identity", run.Fields("boot", identity.Boot, "ticks", int(identity.Ticks)))))
	// as a box the loop is taking down is, part way, while the tick walks its folder
	box := filepath.Join(dir, ".box-1")
	if err := os.Mkdir(box, 0); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(box, 0o700) })
	if !noStallRecovery() {
		t.Fatal("a loop that just wrote was counted silent")
	}
}
