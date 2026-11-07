//go:build linux

package loop

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
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
	if code, said := again(t, "0"); code != 0 {
		t.Fatalf("exit %d\n%s", code, said)
	}
	return false
}

// again is how this test ran again, AK_NOROOM_CHILD its room, in a user namespace of its own: the
// process limit there counts its own tasks alone, never those this user's others start and end.
func again(t *testing.T, room string) (code int, said []byte) {
	child := exec.Command(os.Args[0], "-test.run=^"+t.Name()+"$", "-test.v")
	child.Env = append(os.Environ(), "AK_NOROOM_CHILD="+room)
	child.SysProcAttr = &syscall.SysProcAttr{Cloneflags: syscall.CLONE_NEWUSER,
		UidMappings: []syscall.SysProcIDMap{{ContainerID: os.Getuid(), HostID: os.Getuid(), Size: 1}},
		GidMappings: []syscall.SysProcIDMap{{ContainerID: os.Getgid(), HostID: os.Getgid(), Size: 1}}}
	said, err := child.CombinedOutput()
	if child.ProcessState == nil {
		t.Skipf("no user namespace of its own here: %v", err)
	}
	return child.ProcessState.ExitCode(), said
}

// A driver started where the task table has no room for the threads it holds, full already or
// with room for a process or two, ends as one whose table fills does, its log saying so and its
// run the tick's, where its runtime would die starting those threads.
func TestADriverStartedWithNoRoomLeavesTheRunToTheTick(t *testing.T) {
	if room := os.Getenv("AK_NOROOM_CHILD"); room != "" {
		free, _ := strconv.ParseUint(room, 10, 64)
		leaveRoom(t, free)
		t.Fatalf("the driver went on, to %d", drive(os.Getenv("AGENTKIT_RUN"), nil))
	}
	for _, room := range []string{"0", "2"} {
		l := rig(t, time.Minute)
		code, said := again(t, room)
		if code == 0 {
			t.Skipf("the process limit leaves room to start a process here\n%s", said)
		}
		log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
		if code != 75 || !strings.Contains(string(log), noRoom) {
			t.Fatalf("room for %s: exit %d\n%s\n%s", room, code, said, log)
		}
	}
}

// fillTable leaves this process, its threads held as the driver's are, the room a full task table
// leaves it.
func fillTable(t *testing.T) {
	if err := holdThreads(); err != nil {
		t.Fatal(err)
	}
	leaveRoom(t, 0)
}

// leaveRoom leaves this process the room a task table with room for n more tasks, a thread or a
// process each, leaves it: one below the lowest process limit it starts a process under, plus n.
// One thread at a time runs it first, as holdThreads has the driver: a collection under way on
// every core would start threads the table has no room for, a death before any driver ran.
func leaveRoom(t *testing.T, n uint64) {
	runtime.GOMAXPROCS(1)
	var limit unix.Rlimit
	if err := unix.Getrlimit(unix.RLIMIT_NPROC, &limit); err != nil {
		t.Fatal(err)
	}
	low, high := uint64(1), min(limit.Max, 1<<20)
	for low < high {
		limit.Cur = low + (high-low)/2
		if err := unix.Setrlimit(unix.RLIMIT_NPROC, &limit); err != nil {
			t.Fatal(err)
		}
		switch err := exec.Command("true").Run(); {
		case err == nil:
			high = limit.Cur
		case errors.Is(err, syscall.EAGAIN):
			low = limit.Cur + 1
		default:
			t.Fatal(err)
		}
	}
	if low == 1 {
		t.Skip("the process limit leaves room to start a process here")
	}
	limit.Cur = low - 1 + n
	if err := unix.Setrlimit(unix.RLIMIT_NPROC, &limit); err != nil {
		t.Fatal(err)
	}
}
