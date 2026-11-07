//go:build linux

package loop

import (
	"errors"
	"os"
	"os/exec"
	"sync"
	"syscall"
	"testing"

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

// fillTable leaves this process, its threads held as the driver's are, the room a full task table
// leaves it: none to start a thread or process.
func fillTable(t *testing.T) {
	holdThreads()
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
