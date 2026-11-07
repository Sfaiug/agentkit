//go:build linux

package loop

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// A driver whose task table fills goes on to its next fork, whose error endNoRoom answers, while
// one fewer of its calls block at once than the threads it holds: each blocking call hands the
// driver's one thread's turn to another, one the runtime would die failing to start.
func TestADriverWithNoRoomBlocksOnThreadsItHolds(t *testing.T) {
	if !inChild(t) {
		return
	}
	fillTable(t)
	var blocked sync.WaitGroup
	blocked.Add(heldThreads - 1)
	for range heldThreads - 1 {
		go func() {
			defer blocked.Done()
			unix.Nanosleep(&unix.Timespec{Nsec: 200e6}, nil)
		}()
	}
	blocked.Wait()
}

// inChild reports whether the test runs in the child it runs again in, having failed on that
// child's failure where not: a test leaving no room to start a thread or process does so there,
// as its runtime may then die, and its own process keeps room to read how that child ended.
func inChild(t *testing.T) bool {
	if os.Getenv("AK_NOROOM_CHILD") != "" {
		return true
	}
	child := exec.Command(os.Args[0], "-test.run=^"+t.Name()+"$", "-test.v")
	child.Env = append(os.Environ(), "AK_NOROOM_CHILD=1")
	if said, err := child.CombinedOutput(); err != nil {
		t.Fatalf("%v\n%s", err, said)
	}
	return false
}

// A driver started where the task table is full already ends as one whose table fills does, its
// log saying so and its run the tick's, where its runtime would die starting the threads it holds.
func TestADriverStartedWithNoRoomLeavesTheRunToTheTick(t *testing.T) {
	if os.Getenv("AK_NOROOM_CHILD") != "" {
		leaveNoRoom(t)
		t.Fatalf("the driver went on, to %d", drive(os.Getenv("AGENTKIT_RUN"), nil))
	}
	l := rig(t, time.Minute)
	child := exec.Command(os.Args[0], "-test.run=^"+t.Name()+"$", "-test.v")
	child.Env = append(os.Environ(), "AK_NOROOM_CHILD=1")
	said, err := child.CombinedOutput()
	if err == nil {
		t.Skipf("the process limit leaves room to start a process here\n%s", said)
	}
	log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
	if child.ProcessState.ExitCode() != 75 || !strings.Contains(string(log), noRoom) {
		t.Fatalf("%v\n%s\n%s", err, said, log)
	}
}

// fillTable leaves this process, its threads held as the driver's are, the room a full task table
// leaves it.
func fillTable(t *testing.T) {
	if err := holdThreads(); err != nil {
		t.Fatal(err)
	}
	leaveNoRoom(t)
}

// leaveNoRoom leaves this process the room a full task table leaves it: none to start a thread or
// process.  One thread at a time runs it first, as holdThreads has the driver: a collection under
// way on every core would start threads the table has no room for, a death before any driver ran.
func leaveNoRoom(t *testing.T) {
	runtime.GOMAXPROCS(1)
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
}
