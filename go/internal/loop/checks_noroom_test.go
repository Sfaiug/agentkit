//go:build linux

package loop

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// A check the host has no room to start says nothing of the work: its error reaches the run's end,
// which leaves the run to the tick (noroom.go), where a failed check would start a fixer.  The
// limit is lowered in a child of the test, as its runtime may then fail to start a thread.
func TestACheckWithNoRoomToStartLeavesTheRunToTheTick(t *testing.T) {
	if os.Getenv("AK_NOROOM_CHILD") == "" {
		child := exec.Command(os.Args[0], "-test.run=^"+t.Name()+"$", "-test.v")
		child.Env = append(os.Environ(), "AK_NOROOM_CHILD=1")
		if said, err := child.CombinedOutput(); err != nil {
			t.Fatalf("%v\n%s", err, said)
		}
		return
	}
	l := rig(t, time.Minute)
	oneThreadAtATime()
	var limit unix.Rlimit
	if err := unix.Getrlimit(unix.RLIMIT_NPROC, &limit); err != nil {
		t.Fatal(err)
	}
	limit.Cur = 1
	if err := unix.Setrlimit(unix.RLIMIT_NPROC, &limit); err != nil {
		t.Fatal(err)
	}
	if err := exec.Command("true").Run(); !errors.Is(err, syscall.EAGAIN) {
		t.Skipf("the process limit leaves room to start a process here: %v", err)
	}
	if ok, text, err := l.checks([]string{"true"}, filepath.Join(l.roundDir(), "donewhen.log")); !errors.Is(err, syscall.EAGAIN) {
		t.Fatalf("no room to start a check read as its result: ok=%v err=%v\n%s", ok, err, text)
	}
}
