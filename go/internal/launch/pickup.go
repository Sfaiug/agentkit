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
// pickup_while_queued moves it: its driver reads the installed ak's version as it begins to wait,
// and again after each poll that leaves it waiting.  Where that moved, it says so and execs the
// same launch on the installed ak, which takes up the same receipt: the pid and queued_at, so its
// place in line, stay.  Behind the first its waiter moves it (Waiter).

// program is this program as it started, its links resolved, as Python reads config.REPO once at
// import: an install swaps whole checkouts (update's exchange), after which the running file, read
// again, lies in the retired one, whose version never moves.
var program = func() string {
	self, err := os.Executable()
	if err != nil {
		return ""
	}
	return config.Resolve(self)
}()

// installed is the version installed where this program started, as Python's waiter.head reads it:
// `git -C <the folder above its bin/> rev-parse --short HEAD`.  A read that fails or runs slow is
// no version, which moves nothing, as where Go has no exec (Windows): there a waiting launch stays
// on the code it started on.
func installed() string {
	if program == "" || runtime.GOOS == "windows" {
		return ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	git := exec.CommandContext(ctx, "git", "-C", filepath.Dir(filepath.Dir(program)), "rev-parse", "--short", "HEAD")
	git.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0")
	git.WaitDelay = time.Second
	head, err := git.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(head))
}

// moved is the version installed now where that is no longer on, "" where it is, or either is no
// version.
func moved(on string) string {
	if on != "" {
		if now := installed(); now != "" && now != on {
			return now
		}
	}
	return ""
}

// movable is whether this process may move: it is the run's own detached driver, `ak run --drive`
// with AGENTKIT_RUN_DIR naming the run (loop.Start), and the receipt names no checkout of ak's
// (ak_checkout), whose run stays on it, as Python's pickup_while_queued keeps each.
func movable(dir string, record *run.Object) bool {
	if program == "" || runtime.GOOS == "windows" || os.Getenv("AGENTKIT_RUN_DIR") != dir ||
		!slices.Equal(os.Args[1:], []string{"run", loop.DriveFlag, dir}) ||
		record != nil && record.Truthy("ak_checkout") {
		return false
	}
	current, _ := run.Read(dir)
	return current != nil && !current.Truthy("ak_checkout")
}

// pickUp replaces the run's driver with the same launch on the installed ak where that is no
// longer on, the version this process began to wait on.  It returns only where the process may not
// move (movable), nothing moved, or the system has no exec.
func pickUp(dir string, record *run.Object, on string) {
	if !movable(dir, record) {
		return
	}
	if now := moved(on); now != "" {
		fmt.Printf("%s picked up agentkit %s..%s while waiting for a slot\n", time.Now().Format("[15:04:05]"), on, now)
		syscall.Exec(program, append([]string{program}, os.Args[1:]...), os.Environ())
	}
}
