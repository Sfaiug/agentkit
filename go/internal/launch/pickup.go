package launch

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// A launch waiting for its slot holds nothing, so it moves to new code, as Python's
// pickup_while_queued moves it: once a poll first leaves it waiting its driver reads the installed
// ak's version, and after each poll that leaves it waiting reads it again.  Where that moved, it
// says so and execs the same launch on the installed ak, which takes up the same receipt: the pid
// and queued_at, so its place in line, stay.  Behind the first its waiter moves it (Waiter).

// installed is this program, its links resolved, and the version installed there now, as Python's
// waiter.head reads it: `git -C <the folder above its bin/> rev-parse --short HEAD`.  A read that
// fails or runs slow is no version, which moves nothing, as where Go has no exec (Windows): there a
// waiting launch stays on the code it started on.
func installed() (self, version string) {
	self, _, err := config.Running()
	if err != nil || runtime.GOOS == "windows" {
		return self, ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	head, err := exec.CommandContext(ctx, "git", "-C", filepath.Dir(filepath.Dir(self)), "rev-parse", "--short", "HEAD").Output()
	if err != nil {
		return self, ""
	}
	return self, strings.TrimSpace(string(head))
}

// moved is the installed version and this program where that is no longer on, "" where it is, or
// either is no version.
func moved(on string) (self, now string) {
	if on != "" {
		if self, now = installed(); now != on {
			return self, now
		}
	}
	return self, ""
}

// movable is whether this process may move: it is the run's own driver, `ak run --drive`, which
// nothing else runs in, and the receipt its last poll read names no checkout of ak's (ak_checkout),
// whose run stays on it, as Python's pickup_while_queued keeps both.
func movable(dir string, record *run.Object) bool {
	return slices.Equal(os.Args[1:], []string{"run", loop.DriveFlag, dir}) && !record.Truthy("ak_checkout")
}

// pickUp replaces the run's driver with the same launch on the installed ak where that is no
// longer on, the version this process read as a poll first left it waiting.  It returns only where
// the process may not move (movable), nothing moved, or the system has no exec.
func pickUp(dir string, record *run.Object, on string) {
	if !movable(dir, record) {
		return
	}
	if self, now := moved(on); now != "" {
		fmt.Printf("%s picked up agentkit %s..%s while waiting for a slot\n", time.Now().Format("[15:04:05]"), on, now)
		syscall.Exec(self, os.Args, os.Environ())
	}
}
