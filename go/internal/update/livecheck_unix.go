//go:build unix

package update

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
)

// LiveCheck is `ak live-check <folder>`, Python's LIVE_RUN: the check of agentkit's tests/live.sh
// at the commit folder is named for, `<commit>-<started>`, in a throwaway worktree of it, its
// output and its exit code then each written whole in the folder, as Python's tick reads them.
// Both run in the process group of a holder, a `sleep` it starts first and reaps last, after every
// signal to the group, so the group's id names no other process while it signals it.  Once the
// script exits, KILL to the group ends whatever it left there; at the check's cap, or on TERM,
// TERM, then KILL after the grace, and the code is 124.  The exit code waits, up to the grace,
// until the group is gone.  The worktree is added under the move lock, shared, as a move takes
// away the repository an add names: the lock is taken here and handed to the script as its fd 3,
// which git does not get, and closed once the add ends.
func LiveCheck(folder string) int {
	host.Mark("live check")
	term := make(chan os.Signal, 1)
	signal.Notify(term, syscall.SIGTERM) // from the first: a TERM ends the check, never this
	commit, started, _ := strings.Cut(filepath.Base(folder), "-")
	since, err := strconv.ParseInt(started, 10, 64)
	if err != nil {
		return 2
	}
	os.Setenv("AK_LIVE_FAILED", filepath.Join(folder, "failed"))
	output := filepath.Join(folder, "output")
	out, err := os.Create(output + ".tmp")
	if err != nil {
		return 1
	}
	holder := exec.Command("sleep", "99999999")
	holder.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := holder.Start(); err != nil {
		return 1
	}
	group := holder.Process.Pid
	repo, tree := filepath.Join(config.UserHome(), "agentkit"), filepath.Join(folder, "tree")
	script := exec.Command("sh", "-c", `git -C "$0" worktree add --quiet --detach "$1" "$2" 3>&- && exec 3>&- && cd "$1" && bash tests/live.sh`,
		repo, tree, commit)
	script.Stdout, script.Stderr = out, out
	script.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pgid: group}
	var mu sync.Mutex
	stopped, began, exited := false, false, 0
	done := make(chan struct{})
	go func() {
		defer close(done)
		held, err := lock.Shared(filepath.Join(config.Home(), "tmp", moving))
		if err != nil {
			fmt.Fprintln(out, err)
			exited = 1
			return
		}
		script.ExtraFiles = []*os.File{held}
		// under mu, so nothing starts in the group once it is being ended
		mu.Lock()
		if !stopped {
			err = script.Start()
			began = err == nil
		}
		mu.Unlock()
		held.Close()
		if err != nil {
			fmt.Fprintln(out, err)
			exited = 1
		} else if failed := (*exec.ExitError)(nil); began && errors.As(script.Wait(), &failed) {
			exited = returncode(failed)
		}
	}()
	ran := false
	select {
	case <-done:
		ran = true
	case <-time.After(time.Until(time.Unix(since+liveCap, 0))):
	case <-term:
	}
	mu.Lock()
	stopped = true
	running := began
	mu.Unlock()
	end := func(sig syscall.Signal) { syscall.Kill(-group, sig) }
	code := 124 // as timeout(1) says of what it ended
	if ran {
		code = exited
	} else {
		end(syscall.SIGTERM)
		if running {
			select {
			case <-done:
			case <-time.After(killGrace * time.Second):
			}
		}
	}
	end(syscall.SIGKILL)
	if running {
		<-done
	}
	holder.Wait()
	// a busy host runs what KILL reached only later; past the holder's reaping it only probes
	for gone := time.Now().Add(killGrace * time.Second); time.Now().Before(gone) && syscall.Kill(-group, 0) == nil; {
		time.Sleep(10 * time.Millisecond)
	}
	exec.Command("git", "-C", repo, "worktree", "remove", "--force", tree).Run()
	fmt.Fprintf(out, "[exit %d]\n", code)
	if out.Close() != nil || os.Rename(output+".tmp", output) != nil ||
		put(filepath.Join(folder, "exit"), []byte(fmt.Sprintf("%d\n", code))) != nil {
		return 1
	}
	return 0
}
