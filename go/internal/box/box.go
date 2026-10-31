//go:build linux

// Package box is the worker's walls, as Python's agentkit/box.py builds them, and whether this
// host can start them, asked before a launch makes anything (Check).  It hides
// bubblewrap's arguments: the root read-only, the devices the account may use, a /proc of the
// box's own, the places a command may write, and /run, /tmp, /var/tmp, /dev/shm and the runtime
// directory kept the box's own, empty but for a copy of the host's /run with no socket in it.
// It hides the host's credentials: no GitHub token variable or SSH agent address reaches the
// command, and every credential file and folder of the account reads empty, as does each place
// the caller hides, each through a link too, and none gains another name in /run's copy.
// And it hides the box's first process, this program started again inside, with its report of
// how the command ended: an exit of n is n, a death by a signal keeps that signal, and a command
// that cannot start keeps the shell's 127 or 126.
package box

import (
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"maps"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/commandhelp"
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

// tokens are the variables a box never passes on: GitHub's tokens, and the SSH agent's address.
var tokens = []string{"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "SSH_AUTH_SOCK"}

// credentials are where the account's tools keep theirs, under each home and where env moves
// them: GitHub's logins, Git's stores and caches, and SSH's keys, as a worker reaches no server.
var credentials = []string{"~/.config/gh/hosts.yml", "$XDG_CONFIG_HOME/gh/hosts.yml", "$GH_CONFIG_DIR/hosts.yml",
	"~/.git-credentials", "~/.config/git/credentials", "$XDG_CONFIG_HOME/git/credentials",
	"~/.git-credential-cache", "~/.cache/git/credential", "$XDG_CACHE_HOME/git/credential", "~/.ssh"}

// Run runs argv in a box, its stderr into stderr, and is how it ended (First).
// The box writes only the manifest paths of state for env, made where missing, the targets of
// the links among the manifest paths of logins, the workspace and its git directories, and out;
// the files and folders hidden read empty there, as the account's credentials do.
func Run(argv []string, env map[string]string, workspace, out string, state, logins, hidden []string, stderr *os.File) (int, error) {
	report := filepath.Join(config.Resolve(out), "box-processes.json")
	cmd, done, err := command(append([]string{exe, report}, argv...), env, workspace, out, state, logins, hidden)
	if err != nil {
		return 0, err
	}
	defer done()
	// The running image, not the file at its path, which a build may since have replaced.
	self, err := os.Open("/proc/self/exe")
	if err != nil {
		return 0, err
	}
	defer self.Close()
	os.Remove(report)
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

// command is bubblewrap's command putting argv in the box Run describes, and what removes the
// folder in out holding the box's own places once the box has ended.  With no workspace, as a
// launch has none yet, what env names relative is read from the current folder, and nothing is
// written there.
func command(argv []string, env map[string]string, workspace, out string, state, logins, hidden []string) (*exec.Cmd, func(), error) {
	if _, err := exec.LookPath("bwrap"); err != nil {
		return nil, nil, errors.New("worker box needs bubblewrap; run `" + install + "`")
	}
	for _, path := range transient {
		if info, err := os.Stat(path); err != nil || !info.IsDir() {
			return nil, nil, fmt.Errorf("worker box needs %s: the host directory is missing", path)
		}
	}
	env = maps.Clone(env)
	agent := env["SSH_AUTH_SOCK"]
	for _, key := range tokens {
		delete(env, key)
	}
	out = config.Resolve(out)
	dir, err := filepath.Abs(workspace)
	if err != nil {
		return nil, nil, err
	}
	places, err := writable(env, dir, workspace, out, state, logins)
	if err != nil {
		return nil, nil, err
	}
	hidden, err = masked(env, dir, agent, hidden)
	if err != nil {
		return nil, nil, err
	}
	// Short folders in out: a socket's path in the box still fits beside a long run id.
	scratch, err := os.MkdirTemp(out, ".box-")
	if err != nil {
		return nil, nil, err
	}
	done := func() { os.RemoveAll(scratch) }
	empty, err := own(scratch, env, dir, places, hidden)
	if err != nil {
		done()
		return nil, nil, err
	}
	mounts, err := binds(empty, places)
	if err != nil {
		done()
		return nil, nil, err
	}
	args := append([]string{"--unshare-user", "--unshare-pid", "--as-pid-1", "--die-with-parent", "--new-session"}, walls()...)
	args = append(append(append(args, mounts...), masks(hidden)...), "--")
	env["TMPDIR"] = "/var/tmp"
	cmd := exec.Command("bwrap", append(args, argv...)...)
	for key, value := range env {
		cmd.Env = append(cmd.Env, key+"="+value)
	}
	return cmd, done, nil
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

// writable is every place the box writes through to, its relative manifest paths under dir.
func writable(env map[string]string, dir, workspace, out string, state, logins []string) ([]string, error) {
	var places []string
	for _, path := range config.ManifestPaths(state, env, dir) {
		path = config.Resolve(path)
		if err := os.MkdirAll(path, 0o777); err != nil {
			return nil, err
		}
		places = append(places, path)
	}
	// A login lent as a link is refreshed in place where it leads, and a shared refresh lock
	// lent before its first use is made there, its folder staying read-only.
	for _, path := range config.ManifestPaths(logins, env, dir) {
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
	places = append(places, out)
	if workspace == "" {
		return places, nil
	}
	places = append(places, workspace)
	if _, err := os.Stat(filepath.Join(workspace, ".git")); err != nil {
		return places, nil
	}
	env = maps.Clone(env)
	delete(env, "GIT_DIR")
	delete(env, "GIT_COMMON_DIR")
	delete(env, "GIT_WORK_TREE")
	dirs, err := git(env, workspace, "rev-parse", "--absolute-git-dir", "--git-common-dir")
	if err != nil {
		return nil, fmt.Errorf("git rev-parse in %s: %w", workspace, err)
	}
	for _, dir := range config.SplitLines(dirs) {
		if !filepath.IsAbs(dir) {
			dir = workspace + "/" + dir
		}
		places = append(places, config.Resolve(dir))
	}
	return places, nil
}

// masked is each place the box shows empty, resolved: the account's credentials, the stores
// Git's helpers name, the agent's socket, an address relative to ak's own folder, and hidden,
// each with all it holds through links too, so a file or folder lent from elsewhere hides too.
func masked(env map[string]string, workspace, agent string, hidden []string) ([]string, error) {
	places, err := stores(env, workspace)
	if err != nil {
		return nil, err
	}
	places = append(places, hidden...)
	homes := []string{cmp.Or(env["HOME"], config.UserHome())}
	if account, err := user.Current(); err == nil {
		homes = append(homes, account.HomeDir)
	}
	for _, home := range homes {
		named := maps.Clone(env)
		named["HOME"] = home
		places = append(places, config.ManifestPaths(credentials, named, workspace)...)
	}
	if agent != "" {
		places = append(places, config.Resolve(agent))
	}
	found := map[string]bool{}
	for _, place := range places {
		if err := contents(place, found); err != nil {
			return nil, err
		}
	}
	return slices.Sorted(maps.Keys(found)), nil
}

// contents adds to found the real path of root and of all it holds, through linked folders too,
// each folder listed once; what is missing, loops or lies under a file has none.  A folder the
// account cannot open on the way is a refusal: the command could open one it owns, so what it
// holds stays unknown.
func contents(root string, found map[string]bool) error {
	for pending := []string{root}; len(pending) > 0; {
		path := pending[len(pending)-1]
		pending = pending[:len(pending)-1]
		real, err := filepath.EvalSymlinks(path)
		var entries []fs.DirEntry
		if err == nil && !found[real] {
			found[real] = true
			if info, _ := os.Stat(real); info != nil && info.IsDir() {
				entries, err = os.ReadDir(real)
			}
		}
		failed := &fs.PathError{}
		if errors.Is(err, fs.ErrPermission) && errors.As(err, &failed) {
			shut := config.Resolve(failed.Path)
			for folder := shut; folder != filepath.Dir(folder); {
				folder = filepath.Dir(folder)
				if syscall.Access(folder, 4|1) != nil { // access(2)'s R_OK|X_OK
					shut = folder
				}
			}
			return fmt.Errorf("%s is closed to you, so the worker box cannot see what it must hide there; run `chmod u+rx %s`",
				shut, commandhelp.ShellJoin([]string{shut}))
		}
		for _, entry := range entries {
			pending = append(pending, filepath.Join(real, entry.Name()))
		}
	}
	return nil
}

// variable is a placeholder of Python's string.Template.
var variable = regexp.MustCompile(`(?i)\$(?:(\$)|([_a-z][_a-z0-9]*)|\{([_a-z][_a-z0-9]*)\})`)

// stores are the files and sockets Git's credential helpers keep logins in, asked of Git so its
// includes and a repository's own settings count as Git counts them.  A value its helper line
// quotes whole is taken as it stands; any other has the variables env sets and a leading `~/`
// expanded, as the helper's shell would.
func stores(env map[string]string, workspace string) ([]string, error) {
	helpers, err := git(env, workspace, "config", "--get-regexp", `^credential(\..*)?\.helper$`)
	if err != nil && !errors.As(err, new(*exec.ExitError)) {
		return nil, err
	}
	var places []string
	for _, line := range config.SplitLines(helpers) {
		_, helper, _ := strings.Cut(line, " ")
		words, ok := commandhelp.ShellSplit(helper)
		if !ok || len(words) == 0 || !slices.Contains([]string{"store", "git-credential-store", "cache", "git-credential-cache"}, filepath.Base(words[0])) {
			continue
		}
		flag := "--file"
		if strings.Contains(words[0], "cache") {
			flag = "--socket"
		}
		for i, word := range words[1:] {
			value, named := strings.CutPrefix(word, flag+"=")
			if word == flag && i+2 < len(words) {
				value, named = words[i+2], true
			}
			if !named || value == "" {
				continue
			}
			if !strings.Contains(helper, "'"+value+"'") && !strings.Contains(helper, "'"+flag+"="+value+"'") {
				value = variable.ReplaceAllStringFunc(value, func(match string) string {
					parts := variable.FindStringSubmatch(match)
					if set, ok := env[parts[2]+parts[3]]; ok {
						return set
					} else if parts[1] != "" {
						return "$"
					}
					return match
				})
				if rest, ok := strings.CutPrefix(value, "~/"); ok {
					value = cmp.Or(env["HOME"], config.UserHome()) + "/" + rest
				}
			}
			if !filepath.IsAbs(value) {
				value = workspace + "/" + value
			}
			places = append(places, value)
		}
	}
	return places, nil
}

// masks are bubblewrap's words showing each of the sorted hidden places empty: a folder as an
// empty read-only one, anything else as /dev/null.  One inside a hidden folder is gone already,
// and no mount point can be made there.
func masks(hidden []string) []string {
	var folders, args []string
	for _, path := range hidden {
		if inside(filepath.Dir(path), folders) {
			continue
		} else if info, err := os.Stat(path); err == nil && info.IsDir() {
			folders = append(folders, path)
			args = append(args, "--tmpfs", path, "--remount-ro", path)
		} else {
			args = append(args, "--dev-bind", "/dev/null", path)
		}
	}
	return args
}

// git is what ak's own Git, the first in a folder ak's own PATH names in full, never one the
// workspace puts on the PATH, answers in workspace: its answers open places for writing and say
// what to hide.
func git(env map[string]string, workspace string, args ...string) (string, error) {
	found := ""
	for _, dir := range filepath.SplitList(os.Getenv("PATH")) {
		if filepath.IsAbs(dir) && found == "" {
			found, _ = exec.LookPath(filepath.Join(dir, "git"))
		}
	}
	if found == "" {
		return "", errors.New("worker box needs git in a directory PATH names in full")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, found, args...)
	cmd.Dir = workspace
	for key, value := range env {
		cmd.Env = append(cmd.Env, key+"="+value)
	}
	cmd.Env = append(cmd.Env, "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1")
	answer, err := cmd.Output()
	return string(answer), cmp.Or(ctx.Err(), err)
}

// own is each place the box keeps its own, by its path inside, and its folder in scratch: the
// transient places, /run a copy of the host's, and the runtime directory env names, which env
// then names in that copy, holding nothing hidden.
func own(scratch string, env map[string]string, workspace string, writable, hidden []string) (map[string]string, error) {
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
	if err := copyRun(run, folders[run], scratch, hidden); err != nil {
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
// Nor is anything hidden, by its path or by its device and inode, read as the copy starts: a
// credential replaced by rename since its mask was made gains no other name here either.
func copyRun(source, destination, scratch string, hidden []string) error {
	ids := map[[2]uint64]bool{}
	for _, path := range hidden {
		if info, err := os.Stat(path); err == nil {
			ids[inode(info)] = true
		}
	}
	return filepath.WalkDir(source, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		target := filepath.Join(destination, strings.TrimPrefix(path, source))
		info, err := entry.Info()
		switch {
		case err != nil || ids[inode(info)] || inside(path, hidden) || path == scratch || path == filepath.Join(source, "user"):
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
			return copyFile(path, target, ids)
		}
		return nil
	})
}

// inode is a file's device and inode.
func inode(info fs.FileInfo) [2]uint64 {
	stat := info.Sys().(*syscall.Stat_t)
	return [2]uint64{uint64(stat.Dev), uint64(stat.Ino)}
}

// copyFile copies a regular file, following no link and waiting on no pipe that a service may
// have put in its place meanwhile; one it cannot read through, or that is one of hidden, is
// left out.
func copyFile(path, target string, hidden map[[2]uint64]bool) error {
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil
	}
	defer file.Close()
	if info, err := file.Stat(); err != nil || !info.Mode().IsRegular() || hidden[inode(info)] {
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
