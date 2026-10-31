//go:build linux

// Package box is the worker's walls, as Python's agentkit/box.py builds them.  It hides
// bubblewrap's arguments: the root read-only, the devices the account may use, a /proc of the
// box's own, the places a command may write, and /run, /tmp, /var/tmp, /dev/shm and the runtime
// directory kept the box's own, empty but for a copy of the host's /run with no socket in it.
// And it hides the box's first process, this program started again inside, with its report of
// how the command ended: an exit of n is n, a death by a signal keeps that signal, and a command
// that cannot start keeps the shell's 127 or 126.
package box

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/config"
)

// Supported is whether this system has bubblewrap's box.
const Supported = true

// exeFD is the descriptor bubblewrap inherits this program by, and exe how the box starts it
// there, so its first process runs wherever the binary lives, a place the box hides included.
// Nobody types exe, so it also tells the first process from any `ak` command.
const (
	exeFD = 3
	exe   = "/proc/self/fd/3"
)

// transient are the places the box keeps its own: what the host keeps there stays out, and what
// a command leaves there reaches neither the host nor the next box.
var transient = []string{"/run", "/tmp", "/var/tmp", "/dev/shm"}

// Run runs argv in a box, its stderr into stderr, and is how it ended (First).
// The box writes only the manifest paths of state for env, made where missing, the targets of
// the links among the manifest paths of logins, the workspace and its git directories, and out.
func Run(argv []string, env map[string]string, workspace, out string, state, logins []string, stderr *os.File) (int, error) {
	if _, err := exec.LookPath("bwrap"); err != nil {
		return 0, errors.New("worker box needs bubblewrap; run `sudo apt-get install -y bubblewrap`")
	}
	for _, path := range transient {
		if info, err := os.Stat(path); err != nil || !info.IsDir() {
			return 0, fmt.Errorf("worker box needs %s: the host directory is missing", path)
		}
	}
	out = config.Resolve(out)
	places, err := writable(env, workspace, out, state, logins)
	if err != nil {
		return 0, err
	}
	// Short folders in out: a socket's path in the box still fits beside a long run id.
	scratch, err := os.MkdirTemp(out, ".box-")
	if err != nil {
		return 0, err
	}
	defer os.RemoveAll(scratch)
	env = maps.Clone(env)
	empty, err := own(scratch, env, workspace, places)
	if err != nil {
		return 0, err
	}
	mounts, err := binds(empty, places)
	if err != nil {
		return 0, err
	}
	// The running image, not the file at its path, which a build may since have replaced.
	self, err := os.Open("/proc/self/exe")
	if err != nil {
		return 0, err
	}
	defer self.Close()
	report := filepath.Join(out, "box-processes.json")
	os.Remove(report)
	args := append([]string{"--unshare-user", "--unshare-pid", "--as-pid-1", "--die-with-parent", "--new-session"}, walls()...)
	args = append(append(args, mounts...), "--", exe, report)
	env["TMPDIR"] = "/var/tmp"
	cmd := exec.Command("bwrap", append(args, argv...)...)
	for key, value := range env {
		cmd.Env = append(cmd.Env, key+"="+value)
	}
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, stderr
	cmd.ExtraFiles = []*os.File{self} // exeFD
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := cmd.Run(); err != nil && !errors.As(err, new(*exec.ExitError)) {
		return 0, err
	}
	// Bubblewrap's own status where the first process wrote none: the box never ran the command.
	ended := status(cmd.ProcessState.Sys().(syscall.WaitStatus))
	var written struct{ Returncode *int }
	if data, err := os.ReadFile(report); err == nil && json.Unmarshal(data, &written) == nil && written.Returncode != nil {
		ended = *written.Returncode
	}
	return ended, nil
}

// First is the box's first process, where this program was started as one, and false otherwise:
// it runs the command, writes how it ended to the report, and is the status bubblewrap exits
// with.  As PID 1 its exit ends every process left in the box.
func First() (int, bool) {
	if len(os.Args) < 3 || os.Args[0] != exe {
		return 0, false
	}
	syscall.CloseOnExec(exeFD)
	code, err := run(os.Args[2:])
	if err == nil {
		err = os.WriteFile(os.Args[1], fmt.Appendf(nil, `{"returncode": %d}`, code), 0o666)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1, true
	}
	if code < 0 {
		return 128 - code, true
	}
	return code, true
}

// run starts the command in a session of its own and waits for it, reaping meanwhile the orphans
// a PID 1 inherits: its status, or the shell's 127 or 126 where it could not start.
func run(argv []string) (int, error) {
	command, err := os.StartProcess(argv[0], argv, &os.ProcAttr{
		Files: []*os.File{os.Stdin, os.Stdout, os.Stderr},
		Sys:   &syscall.SysProcAttr{Setsid: true},
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		if errors.Is(err, fs.ErrNotExist) {
			return 127, nil
		}
		return 126, nil
	}
	for {
		var ended syscall.WaitStatus
		pid, err := syscall.Wait4(-1, &ended, 0, nil)
		if pid == command.Pid {
			return status(ended), nil
		} else if err != nil && !errors.Is(err, syscall.EINTR) {
			return 0, err
		}
	}
}

// status is a process's exit status, or its killing signal's number negated.
func status(ended syscall.WaitStatus) int {
	if ended.Signaled() {
		return -int(ended.Signal())
	}
	return ended.ExitStatus()
}

// walls make the whole filesystem read-only, with a /proc of the box's own.  A read-only bind
// disables devices too: bubblewrap's /dev holds the standard nodes, and the account's own come
// back, those it may read or write, a device it may not being of no use outside either.
func walls() []string {
	const read, write = 4, 2 // access(2)'s R_OK and W_OK: no device is opened to find out
	args := []string{"--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"}
	filepath.WalkDir("/dev", func(path string, entry fs.DirEntry, err error) error {
		switch {
		case err != nil:
			return nil
		// The box's /dev/shm is its own; ptmx needs the devpts mount bubblewrap supplies with it.
		case entry.IsDir() && (path == "/dev/shm" || path == "/dev/pts"):
			return fs.SkipDir
		case entry.Type()&fs.ModeDevice != 0 && path != "/dev/ptmx" &&
			(syscall.Access(path, read) == nil || syscall.Access(path, write) == nil):
			args = append(args, "--dev-bind", path, path)
		}
		return nil
	})
	return append(args, "--remount-ro", "/dev")
}

// writable is every place the box writes through to.
func writable(env map[string]string, workspace, out string, state, logins []string) ([]string, error) {
	var places []string
	for _, path := range config.ManifestPaths(state, env, workspace) {
		path = config.Resolve(path)
		if err := os.MkdirAll(path, 0o777); err != nil {
			return nil, err
		}
		places = append(places, path)
	}
	// A login lent as a link is refreshed in place where it leads, and a shared refresh lock
	// lent before its first use is made there, its folder staying read-only.
	for _, path := range config.ManifestPaths(logins, env, workspace) {
		if info, err := os.Lstat(path); err != nil || info.Mode()&fs.ModeSymlink == 0 {
			continue
		}
		target := config.Resolve(path)
		if _, err := os.Stat(target); err != nil {
			if err := os.MkdirAll(filepath.Dir(target), 0o777); err != nil {
				return nil, err
			}
			made, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY, 0o666)
			if err != nil {
				return nil, err
			}
			made.Close()
		}
		places = append(places, target)
	}
	places = append(places, workspace, out)
	if _, err := os.Stat(filepath.Join(workspace, ".git")); err != nil {
		return places, nil
	}
	// Asked of ak's own git, the first in a folder ak's own PATH names in full, never one the
	// workspace puts on the PATH: its answer opens places for writing.
	git := ""
	for _, dir := range filepath.SplitList(os.Getenv("PATH")) {
		if filepath.IsAbs(dir) && git == "" {
			git, _ = exec.LookPath(filepath.Join(dir, "git"))
		}
	}
	if git == "" {
		return nil, errors.New("worker box needs git in a directory PATH names in full")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, git, "rev-parse", "--absolute-git-dir", "--git-common-dir")
	cmd.Dir = workspace
	for key, value := range env {
		if key != "GIT_DIR" && key != "GIT_COMMON_DIR" && key != "GIT_WORK_TREE" {
			cmd.Env = append(cmd.Env, key+"="+value)
		}
	}
	cmd.Env = append(cmd.Env, "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1")
	dirs, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("git rev-parse in %s: %w", workspace, err)
	}
	for _, dir := range config.SplitLines(string(dirs)) {
		if !filepath.IsAbs(dir) {
			dir = workspace + "/" + dir
		}
		places = append(places, config.Resolve(dir))
	}
	return places, nil
}

// own is each place the box keeps its own, by its path inside, and its folder in scratch: the
// transient places, /run a copy of the host's, and the runtime directory env names, which env
// then names in that copy.
func own(scratch string, env map[string]string, workspace string, writable []string) (map[string]string, error) {
	var places []string
	for _, path := range transient {
		places = append(places, config.Resolve(path))
	}
	// One inside a transient place is empty already, unless a writable place shows it again.
	for _, path := range config.ManifestPaths([]string{"$XDG_RUNTIME_DIR"}, env, workspace) {
		real := config.Resolve(path)
		if info, err := os.Stat(path); err == nil && info.IsDir() && (!inside(real, places) || inside(real, writable)) {
			places = append(places, real)
		}
	}
	// Bubblewrap's /dev has a shm folder even where the host's links into /run.
	places = append(places, "/dev/shm")
	slices.Sort(places)
	folders := map[string]string{}
	for i, path := range slices.Compact(places) {
		folders[path] = filepath.Join(scratch, strconv.Itoa(i))
		if err := os.MkdirAll(folders[path], 0o777); err != nil {
			return nil, err
		}
	}
	run := config.Resolve("/run")
	if err := copyRun(run, folders[run], scratch); err != nil {
		return nil, err
	}
	runtime := filepath.Join("user", strconv.Itoa(os.Getuid()))
	folders[filepath.Join(run, runtime)] = filepath.Join(folders[run], runtime)
	if err := os.Mkdir(filepath.Join(folders[run], "user"), 0o777); err != nil {
		return nil, err
	}
	if err := os.Mkdir(filepath.Join(folders[run], runtime), 0o700); err != nil {
		return nil, err
	}
	env["XDG_RUNTIME_DIR"] = filepath.Join("/run", runtime)
	return folders, nil
}

// inside is whether path is one of places or under one.
func inside(path string, places []string) bool {
	for _, place := range places {
		if path == place || strings.HasPrefix(path, strings.TrimSuffix(place, "/")+"/") {
			return true
		}
	}
	return false
}

// copyRun copies the host's /run into its folder without what listens or waits there: folders,
// links and regular files only, and nothing of its `user`, every account's runtime directory.  A
// folder the account cannot read is copied empty, and scratch, where /run holds out, not at all.
func copyRun(source, destination, scratch string) error {
	return filepath.WalkDir(source, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		target := filepath.Join(destination, strings.TrimPrefix(path, source))
		switch {
		case path == scratch || path == filepath.Join(source, "user"):
			if entry.IsDir() {
				return fs.SkipDir
			}
		case entry.IsDir():
			return os.MkdirAll(target, 0o777)
		case entry.Type()&fs.ModeSymlink != 0:
			if link, err := os.Readlink(path); err == nil {
				return os.Symlink(link, target)
			}
		case entry.Type().IsRegular():
			return copyFile(path, target)
		}
		return nil
	})
}

// copyFile copies a regular file, following no link and waiting on no pipe that a service may
// have put in its place meanwhile; one it cannot read through is left out.
func copyFile(path, target string) error {
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil
	}
	defer file.Close()
	if info, err := file.Stat(); err != nil || !info.Mode().IsRegular() {
		return nil
	}
	copied, err := os.Create(target)
	if err != nil {
		return err
	}
	defer copied.Close()
	if _, err := io.Copy(copied, file); err != nil {
		os.Remove(target)
	}
	return nil
}

// binds are bubblewrap's mounts: each own place's folder at its path and each writable place at
// its own, parents first so a deeper mount wins, and none that a parent's mount already shows.
func binds(own map[string]string, writable []string) ([]string, error) {
	shown := maps.Clone(own)
	for _, path := range slices.Sorted(slices.Values(writable)) {
		if _, clash := own[path]; clash {
			return nil, fmt.Errorf("%s is a place the box keeps empty and one it writes through to; give each a directory of its own", path)
		}
		shown[path] = path
	}
	var args []string
	for _, path := range slices.Sorted(maps.Keys(shown)) {
		parent, found := path, false
		for parent != "/" && !found {
			parent = filepath.Dir(parent)
			_, found = shown[parent]
		}
		if !found || filepath.Join(shown[parent], strings.TrimPrefix(path, parent)) != shown[path] {
			args = append(args, "--bind", shown[path], path)
		}
	}
	return args, nil
}
