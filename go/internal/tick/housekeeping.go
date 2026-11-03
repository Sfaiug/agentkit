package tick

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// gcEvery is how often a repository is collected, Python's gc.GC_INTERVAL.
const gcEvery = 86400

// housekeeping is the git housekeeping row on a home with no run and no seat
// (gc.git_housekeeping): each checkout's repository once, kept from collecting itself and
// collected in the foreground once a day while nothing holds it; a busy one waits for a later
// tick.
func (t *ticking) housekeeping() error {
	checkouts, _ := seat.Checkouts()
	slices.Sort(checkouts)
	seen := map[string]bool{}
	for _, repo := range checkouts {
		common, ok := seat.Common(repo)
		if !ok || seen[common] {
			continue
		}
		seen[common] = true
		if err := t.collect(repo, common); err != nil {
			t.log.line(fmt.Sprintf("WARN git gc could not run in %s: %s", repo, config.PyError(err)))
		}
	}
	return nil
}

func (t *ticking) collect(repo, common string) error {
	if err := noAutoGC(repo, common); err != nil {
		return err
	}
	// a worktree being made holds it, and is no time to collect
	held, err := lock.Try(common)
	if errors.Is(err, lock.ErrHeld) {
		return nil
	}
	if err != nil {
		return err
	}
	defer held.Close()
	mark, now := filepath.Join(common, "ak-gc"), epoch(t.clock())
	if data, err := os.ReadFile(mark); err == nil {
		if at, err := strconv.ParseFloat(gitcall.Strip(string(data)), 64); err == nil && now-gcEvery < at && at <= now {
			return nil
		}
	}
	paths, known, err := busyPaths()
	if err != nil {
		return err
	}
	trees := worktrees(repo)
	if !known || len(trees) == 0 || slices.ContainsFunc(trees, func(tree string) bool {
		return slices.ContainsFunc(paths, func(path string) bool { return path == tree || strings.HasPrefix(path, tree+"/") })
	}) {
		return nil
	}
	// attempts are marked too: a failed gc must not run on every tick
	if err := os.WriteFile(mark, []byte(string(run.Float(now))+"\n"), 0o666); err != nil {
		return err
	}
	env, err := config.ChildEnv()
	if err != nil {
		return err
	}
	gc := exec.Command("git", "-C", repo, "gc")
	gc.Env = gitless(env)
	err = gc.Run()
	var exit *exec.ExitError
	switch {
	case errors.As(err, &exit):
		t.log.line(fmt.Sprintf("WARN git gc failed in %s (exit %d)", repo, exitCode(exit)))
	case err != nil:
		return err
	default:
		t.log.line("git gc: " + repo)
	}
	return nil
}

// noAutoGC keeps git from collecting the repository by itself (gitcall.no_auto_gc): a turn's
// detached gc can lock every linked worktree's HEAD, then leave those locks behind when the
// worker stops its leftover processes. Shared, as a worktree being made holds it: only a
// collection waits for nobody.
func noAutoGC(repo, common string) error {
	held, err := lock.Shared(common)
	if err != nil {
		return err
	}
	defer held.Close()
	g := gitcall.Git{Repo: repo, Env: gitcall.ProjectEnv(repo)}
	for _, setting := range [][2]string{{"gc.auto", "0"}, {"maintenance.auto", "false"}} {
		key, value := setting[0], setting[1]
		for _, where := range []string{"--local", "--worktree"} {
			read := []string{"config", "--get", key}
			if where == "--local" {
				read = []string{"config", "--local", "--get", key}
			}
			if now, err := g.Try(read...); err != nil {
				return err
			} else if now == value {
				continue
			}
			if _, err := g.Must("config", where, "--replace-all", key, value); err != nil {
				return err
			}
		}
	}
	return nil
}

// worktrees is every checkout of the repository, none where git cannot say (orch.git_in).
func worktrees(repo string) []string {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	list := exec.CommandContext(ctx, "git", "worktree", "list", "--porcelain", "-z")
	list.Dir = repo
	list.Env = append(gitless(os.Environ()), "GIT_CEILING_DIRECTORIES="+filepath.Dir(config.Absolute(repo)))
	out, err := list.Output()
	if err != nil {
		return nil
	}
	var trees []string
	for _, field := range bytes.Split(out, []byte{0}) {
		if tree, ok := bytes.CutPrefix(field, []byte("worktree ")); ok {
			trees = append(trees, string(tree))
		}
	}
	return trees
}

// busyPaths is every path a process of this user holds (gc.git_busy_paths, on a home with no run
// and no seat): its working directory and open files, and of one hiding those, as a login's own
// daemons do, the absolute words of its command line. Not known where one hides even that.
func busyPaths() (paths []string, known bool, err error) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, false, err
	}
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil || pid == os.Getpid() || !own(pid) {
			continue
		}
		held, args, err := holds(pid)
		if err == nil {
			paths = append(paths, held...)
			continue
		}
		if missing("/proc/" + entry.Name()) {
			continue // it exited
		}
		if args == nil {
			return nil, false, nil
		}
		for _, arg := range args {
			if strings.HasPrefix(arg, "/") {
				paths = append(paths, arg)
			}
		}
	}
	return paths, true, nil
}

// own is whether the process runs as this user: its effective uid, which a process hiding the
// rest of its /proc folder still shows.
func own(pid int) bool {
	status, err := os.ReadFile(fmt.Sprintf("/proc/%d/status", pid))
	for _, line := range strings.Split(string(status), "\n") {
		if ids, ok := strings.CutPrefix(line, "Uid:"); ok && err == nil {
			fields := strings.Fields(ids)
			return len(fields) > 1 && fields[1] == strconv.Itoa(os.Getuid())
		}
	}
	return false
}

// holds is what the process holds (proc_snapshot.collect): its working directory and every file
// it has open, nothing for a zombie or a kernel thread; else an error, with its command line
// where that much was read, and none where the pid named another process by the end.
func holds(pid int) ([]string, []string, error) {
	first, ok := host.ReadStat(pid)
	if !ok {
		return nil, nil, errors.New("no stat to read")
	}
	if first.Exited() || first.Flags&0x200000 != 0 { // PF_KTHREAD
		return nil, nil, nil
	}
	proc := "/proc/" + strconv.Itoa(pid)
	cmdline, err := os.ReadFile(proc + "/cmdline")
	if err != nil {
		return nil, nil, err
	}
	args := slices.DeleteFunc(strings.Split(string(cmdline), "\x00"), func(arg string) bool { return arg == "" })
	cwd, err := os.Readlink(proc + "/cwd")
	if err != nil {
		return nil, args, err
	}
	links := []string{cwd}
	fds, err := os.ReadDir(proc + "/fd")
	if err != nil {
		return nil, args, err
	}
	for _, fd := range fds {
		target, err := os.Readlink(proc + "/fd/" + fd.Name())
		if errors.Is(err, fs.ErrNotExist) {
			continue // closed since
		}
		if err != nil {
			return nil, args, err
		}
		links = append(links, target)
	}
	if again, ok := host.ReadStat(pid); !ok || again.Start != first.Start {
		return nil, nil, errors.New("pid was reused during the scan")
	}
	var held []string
	for _, target := range links {
		if strings.HasPrefix(target, "/") {
			held = append(held, strings.TrimSuffix(target, " (deleted)"))
		}
	}
	return held, args, nil
}
