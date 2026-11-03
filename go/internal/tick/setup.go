package tick

import (
	"bufio"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"syscall"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// A project's `setup:` makes this machine ready for it (Python's machine_setup): the one
// executable file of its default branch that line names, run once on each machine for each
// version of the line and the file, and on every tick after a try that failed. It runs in the
// background, one at a time per project, from that commit's own files, in the checkout.

// setupTail is how many of a failed setup's last lines are kept.
const setupTail = 10

// setupClean is git reading a fresh clone with no setting but its own: neither the checkout's
// `.git` nor the user's changes what runs.
var setupClean = []string{"GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_COUNT=1",
	"GIT_CONFIG_KEY_0=core.attributesFile", "GIT_CONFIG_VALUE_0=/dev/null"}

// SetupVerb is the unlisted command the tick starts a due setup with: `ak machine-setup
// <checkout>`.
const SetupVerb = "machine-setup"

// setups is the project setups row: each checkout's setup that is due here, started in the
// background, unmarked, as it outlives the tick on purpose.
func setups() error {
	checkouts, _ := seat.Checkouts()
	for _, repo := range checkouts {
		held, err := setupLock(repo)
		if errors.Is(err, lock.ErrHeld) {
			continue // its setup is running
		}
		if err != nil {
			return err
		}
		version, _, err := setupDue(repo)
		held.Close()
		if err != nil {
			return err
		}
		if version == nil {
			continue
		}
		self, err := os.Executable()
		if err != nil {
			return err
		}
		env, err := config.ChildEnv()
		if err != nil {
			return err
		}
		start := exec.Command(self, SetupVerb, repo)
		start.Env = slices.DeleteFunc(env, func(pair string) bool {
			return strings.HasPrefix(pair, "AK_OWNER=") || strings.HasPrefix(pair, "AK_TMUX_OWNER=")
		})
		start.SysProcAttr = host.Detached()
		if err := start.Start(); err != nil {
			return err
		}
		start.Process.Release()
	}
	return nil
}

// SetUp is `ak machine-setup <checkout>`: its setup, where it is due and none runs.
func SetUp(args []string) int {
	if len(args) != 1 {
		return 2
	}
	repo := args[0]
	held, err := setupLock(repo)
	if errors.Is(err, lock.ErrHeld) {
		return 0
	}
	if err != nil {
		return 1
	}
	defer held.Close()
	version, commit, err := setupDue(repo)
	if err != nil {
		return 1
	}
	if version == nil {
		return 0
	}
	failed, err := setupRun(repo, commit, version[1].(string), version[2].(string))
	if err != nil {
		return 1
	}
	record := run.NewObject()
	record.Set("version", version)
	if failed != nil {
		record.Set("failed", failed)
	}
	if replaceFile(setupFile(repo, ".json"), run.Line(record)) != nil {
		return 1
	}
	return 0
}

func setupFile(repo, suffix string) string {
	return filepath.Join(config.Home(), "state", "setup", filepath.Base(repo)+suffix)
}

// setupLock is the project's setup lock, held, or ErrHeld while its setup runs.
func setupLock(repo string) (*os.File, error) {
	if err := os.MkdirAll(filepath.Dir(setupFile(repo, "")), 0o777); err != nil {
		return nil, err
	}
	return lock.Try(setupFile(repo, ".lock"))
}

// setupDue is the setup's version here, [machine, line, the file's ls-tree entry], and the
// default branch's commit, where it has yet to pass at that version on this machine; nothing
// where it has. A project naming no setup forgets its last one.
func setupDue(repo string) ([]any, string, error) {
	// the commit as recorded: no local replacement of its objects
	env := append(gitcall.ProjectEnv(repo), "GIT_NO_REPLACE_OBJECTS=1")
	g := gitcall.Git{Repo: repo, Env: env}
	commit, err := g.Try("rev-parse", "--verify", "--quiet", rulesRef)
	if err != nil {
		return nil, "", err
	}
	line := ""
	if commit != "" {
		line = gitcall.DeclaredAt(repo, commit, "setup", env...)
	}
	if line == "" {
		if err := os.Remove(setupFile(repo, ".json")); !errors.Is(err, fs.ErrNotExist) {
			return nil, "", err
		}
		return nil, "", nil
	}
	// git reads `..`, `.`, `//` and a path into the checkout as another path and descends no
	// link, so only an entry it names back as the line itself is a file of the commit's own
	named, err := g.Try("--literal-pathspecs", "ls-tree", "-z", "--full-tree", commit, "--", line)
	if err != nil {
		return nil, "", err
	}
	entry, path, _ := strings.Cut(named, "\t")
	if path != line+"\x00" {
		entry = ""
	}
	machine, err := os.ReadFile("/etc/machine-id")
	if err != nil {
		return nil, "", err
	}
	version := []any{gitcall.Strip(string(machine)), line, entry}
	passed := run.NewObject()
	passed.Set("version", version)
	if data, err := os.ReadFile(setupFile(repo, ".json")); err == nil {
		if last, err := run.Decode(data); err == nil && run.Line(last) == run.Line(passed) {
			return nil, "", nil
		}
	}
	return version, commit, nil
}

// setupRun is nothing where the file line names at commit ran in the checkout and passed, else
// what went wrong and its last lines. It runs from a fresh clone of that commit, its `.git`
// removed, which is removed once it ends: what the commit records, whatever the checkout holds.
func setupRun(repo, commit, line, entry string) ([]any, error) {
	if !strings.HasPrefix(entry, "100") { // a link, a directory or nothing: no file of its own
		return []any{"the default branch holds no " + line}, nil
	}
	scratch, err := os.MkdirTemp(filepath.Join(config.Home(), "tmp"), "setup-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(scratch)
	tree := filepath.Join(scratch, "tree")
	var env []string
	for _, pair := range os.Environ() {
		if key, _, _ := strings.Cut(pair, "="); strings.HasPrefix(key, "GIT_") {
			env = append(env, key)
		}
	}
	env = append(env, setupClean...)
	for _, step := range []struct {
		at   string
		args []string
	}{
		{repo, []string{"clone", "--quiet", "--shared", "--no-checkout", "--", repo, tree}},
		{tree, []string{"checkout", "--quiet", "--detach", commit}},
	} {
		code, said, err := gitcall.Git{Repo: step.at, Env: env}.Out(step.args...)
		if err != nil {
			return nil, err
		}
		if code != 0 {
			return append([]any{fmt.Sprintf("%s cannot start: git %s failed", line, step.args[0])}, last(config.SplitLines(said))...), nil
		}
	}
	if err := os.RemoveAll(filepath.Join(tree, ".git")); err != nil {
		return nil, err
	}
	// by its path alone, as Python's exec takes it: no look along PATH and no check of its own
	program := filepath.Join(tree, line)
	setup := &exec.Cmd{Path: program, Args: []string{program}, Dir: repo}
	said, err := setup.StdoutPipe()
	if err != nil {
		return nil, err
	}
	setup.Stderr = setup.Stdout
	if err := setup.Start(); err != nil {
		var errno syscall.Errno
		if !errors.As(err, &errno) {
			return nil, err
		}
		text := errno.Error()
		return []any{fmt.Sprintf("%s cannot start: %s%s", line, strings.ToUpper(text[:1]), text[1:])}, nil
	}
	var lines []string
	for reader := bufio.NewReader(said); ; {
		read, err := reader.ReadString('\n')
		if read != "" {
			lines = append(lines[max(0, len(lines)+1-setupTail):], strings.TrimRightFunc(gitcall.Decoded(read), config.Space))
		}
		if err != nil {
			break
		}
	}
	var exit *exec.ExitError
	if err := setup.Wait(); errors.As(err, &exit) {
		return append([]any{fmt.Sprintf("%s exited %d", line, exitCode(exit))}, last(lines)...), nil
	} else if err != nil {
		return nil, err
	}
	return nil, nil
}

// last is the last setupTail lines.
func last(lines []string) []any {
	var kept []any
	for _, line := range lines[max(0, len(lines)-setupTail):] {
		kept = append(kept, line)
	}
	return kept
}

// exitCode is a program's exit as Python's returncode says it: the signal that ended it, negative.
func exitCode(exit *exec.ExitError) int {
	if status, ok := exit.Sys().(syscall.WaitStatus); ok && status.Signaled() {
		return -int(status.Signal())
	}
	return exit.ExitCode()
}
