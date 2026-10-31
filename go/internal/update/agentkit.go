package update

import (
	"bytes"
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
)

const (
	moving    = "agentkit-update.lock" // Python's update.MOVING, under tmp: held by each move of ~/agentkit
	upgrades  = "harness-update.lock"  // under tmp: held by each harness upgrade
	stepCap   = 30 * time.Minute       // Python's STEP_CAP, and versions.CAP for each git step of a swap
	gitCap    = time.Minute            // Python's _git, and its FETCH_CAP
	liveCap   = 2 * 60 * 60            // seconds a check of tests/live.sh may run: Python's LIVE_CAP
	killGrace = 10                     // seconds a check's group gets after TERM: worker.MARK_KILL_GRACE
	locked    = "a version of ak's"    // why each version's record is locked, kept from any prune
)

// updateSelf moves ~/agentkit at checkout as Python's update_self does once it has one: what the
// move said, a failure only the first time for each origin commit, and its exit code.
func updateSelf(env []string, checkout string, out io.Writer) int {
	var said bytes.Buffer
	code := moveAgentkit(env, checkout, &said)
	if code != 0 {
		// a refusal comes before any pull, so origin is asked afresh: a stale origin/main would
		// hold a new commit to the one already said
		git(env, checkout, "fetch", "--quiet", "origin", "main")
		head, _ := git(env, checkout, "rev-parse", "origin/main")
		record := filepath.Join(config.Home(), "state", "agentkit-said-update")
		if last, err := os.ReadFile(record); err == nil && strings.TrimFunc(string(last), config.Space) == head {
			return code
		}
		os.WriteFile(record, []byte(head+"\n"), 0o666)
	}
	for _, line := range config.SplitLines(said.String()) {
		fmt.Fprintln(out, line)
	}
	return code
}

// moveAgentkit is Python's update_agentkit: ~/agentkit forward on main to liveTarget, swapped
// in whole, then its install.sh; the exit code.  A checkout that is somebody's work is left as
// it is, saying so.
func moveAgentkit(env []string, checkout string, out io.Writer) int {
	tmp := filepath.Join(config.Home(), "tmp")
	held, err := lock.Wait(context.Background(), filepath.Join(tmp, moving))
	if err != nil {
		fmt.Fprintf(out, "update: %s\n", pyError(err))
		return 1
	}
	defer held.Close()
	if why := leftAsIs(env, checkout); why != "" {
		fmt.Fprintf(out, "update: agentkit: left as it is: %s is %s\n", checkout, why)
		return 1
	}
	upgrade, err := lock.Try(filepath.Join(tmp, upgrades))
	if err != nil {
		// asked under the move's lock, which an upgrade waits for before it begins, so its gates
		// test one commit from start to end
		fmt.Fprintln(out, "update: agentkit: moves once the harness upgrade running now ends")
		return 0
	}
	upgrade.Close()
	if code := step(env, out, "git", "-C", checkout, "fetch", "--quiet", "origin", "main"); code != 0 {
		return code
	}
	target := liveTarget(env, checkout)
	if target == "" {
		fmt.Fprintln(out, "update: agentkit: origin/main moves here once its tests/live.sh passed")
		return 0
	}
	fmt.Fprintf(out, "update: %s goes to %s\n", checkout, short(target))
	// here until install.sh passes: the swap moves HEAD, so origin/main is no longer ahead of
	// it, and only this says the install is owed
	pending := filepath.Join(config.Home(), "state", "agentkit-install-pending")
	if err := os.WriteFile(pending, nil, 0o666); err != nil {
		fmt.Fprintf(out, "update: %s\n", pyError(err))
		return 1
	}
	if why := swap(env, checkout, target); why != "" {
		fmt.Fprintf(out, "update: %s\n", why)
		return 1
	}
	if code := step(env, out, filepath.Join(checkout, "install.sh")); code != 0 {
		return code
	}
	os.Remove(pending)
	return 0
}

// step runs one command of the move as Python's update_agentkit does: said before it runs, what
// it printed after, and its exit code.
func step(env []string, out io.Writer, argv ...string) int {
	fmt.Fprintf(out, "update: $ %s\n", commandhelp.ShellJoin(argv))
	stdout, stderr, code, err := output(env, stepCap, argv...)
	if err != nil {
		fmt.Fprintf(out, "update: %s\n", failure(err, argv, stepCap))
		return 1
	}
	for _, text := range [][]byte{stdout, stderr} {
		for _, line := range config.SplitLines(string(text)) {
			fmt.Fprintln(out, line)
		}
	}
	if code != 0 {
		fmt.Fprintf(out, "update: %s exited %d\n", commandhelp.ShellJoin(argv), code)
	}
	return code
}

// git is one git command in checkout as Python's update._git runs it: what it printed, stripped,
// "" where it could not run, and whether it exited 0.
func git(env []string, checkout string, args ...string) (string, bool) {
	stdout, _, code, err := output(env, gitCap, append([]string{"git", "-C", checkout}, args...)...)
	if err != nil {
		return "", false
	}
	return strings.TrimFunc(string(stdout), config.Space), code == 0
}

// leftAsIs is why ~/agentkit is somebody's work, as Python's left_as_is says it: `dirty`, or on
// another branch; "" for main as origin left it, or a version ak swapped in, which a move swaps.
func leftAsIs(env []string, checkout string) string {
	if owned(checkout) != "" {
		return ""
	}
	branch, _ := git(env, checkout, "symbolic-ref", "--quiet", "--short", "HEAD")
	changes, ok := git(env, checkout, "status", "--porcelain", "--untracked-files=normal")
	if branch != "main" {
		return "on " + cmp.Or(branch, "a detached HEAD") + ", not main"
	}
	if !ok || changes != "" {
		return "dirty"
	}
	return ""
}

// liveTarget is the commit a move of ~/agentkit goes to, as Python's live_target, or "" while
// there is none.  origin/main when the checkout has it already, when it holds no tests/live.sh,
// or when a check of it passed; else the newest commit after HEAD whose check passed, so what
// moves is exactly what passed, however far origin/main has gone on since.
func liveTarget(env []string, checkout string) string {
	tip, _ := git(env, checkout, "rev-parse", "--verify", "--quiet", "origin/main")
	passed := passedChecks()
	if tip == "" || passed[tip] {
		return tip
	}
	if _, ok := git(env, checkout, "cat-file", "-e", tip+":tests/live.sh"); !ok {
		return tip
	}
	if _, ok := git(env, checkout, "merge-base", "--is-ancestor", tip, "HEAD"); ok {
		return tip
	}
	if len(passed) == 0 {
		return ""
	}
	newer, _ := git(env, checkout, "rev-list", "--topo-order", "HEAD.."+tip)
	for _, commit := range strings.FieldsFunc(newer, config.Space) {
		if passed[commit] {
			return commit
		}
	}
	return ""
}

// passedChecks are the commits a check of tests/live.sh passed, from the folders the tick keeps
// under state/live-checks, `<commit>-<started>` each, as Python's live_checks and _live_passed
// read them: one with anything of it still running has no verdict yet, and its verdict is read
// only once the scan for that is over, so one the tick stops meanwhile reads `stopped`.
func passedChecks() map[string]bool {
	checks := filepath.Join(config.Home(), "state", "live-checks")
	entries, _ := os.ReadDir(checks)
	passed := map[string]bool{}
	for _, entry := range entries {
		commit, started, _ := strings.Cut(entry.Name(), "-")
		at, err := strconv.ParseInt(started, 10, 64)
		if err != nil || !config.Digits(started) {
			continue
		}
		check := filepath.Join(checks, entry.Name())
		if alive(check, at) {
			continue
		}
		if code, ended := exitCode(check, at); ended && (code == 0 || failedLabels(check) && exists(filepath.Join(check, "baseline"))) {
			passed[commit] = true
		}
	}
	return passed
}

// exitCode is a check's exit code as Python's update._exit reads it, and whether it has one: one
// written after the check's cap is none, and so is any once the tick wrote `stopped`.
func exitCode(check string, started int64) (int, bool) {
	if exists(filepath.Join(check, "stopped")) {
		return 0, false
	}
	exit := filepath.Join(check, "exit")
	info, err := os.Stat(exit)
	if err != nil || !info.ModTime().Before(time.Unix(started+liveCap, 0)) {
		return 0, false
	}
	data, err := os.ReadFile(exit)
	if err != nil {
		return 0, false
	}
	code, err := strconv.Atoi(strings.TrimFunc(string(data), config.Space))
	return code, err == nil
}

// alive is whether anything of a check still runs, as Python's update._alive: whatever carries
// its marker, where /proc says, else until it has an exit code or its cap and grace have passed.
func alive(check string, started int64) bool {
	if info, err := os.Stat("/proc"); err == nil && info.IsDir() {
		return len(host.Marked(check)) > 0
	}
	_, ended := exitCode(check, started)
	return !ended && time.Now().Unix() < started+liveCap+killGrace
}

// failedLabels is whether a check's suite wrote the label of any test that failed.
func failedLabels(check string) bool {
	data, err := os.ReadFile(filepath.Join(check, "failed"))
	return err == nil && utf8.Valid(data) && slices.ContainsFunc(config.SplitLines(string(data)),
		func(line string) bool { return line != "" })
}

// failure is why a command ran to no exit code, as Python's subprocess says it.
func failure(err error, argv []string, limit time.Duration) string {
	if errors.Is(err, context.DeadlineExceeded) {
		words := make([]string, len(argv))
		for i, word := range argv {
			words[i] = commandhelp.Quote(word)
		}
		return fmt.Sprintf("Command '[%s]' timed out after %d seconds", strings.Join(words, ", "), int(limit.Seconds()))
	}
	return pyError(err)
}

// pyError is err as Python's OSError says it: `[Errno 2] No such file or directory: 'a'`, with
// ` -> 'b'` after for a second path.
func pyError(err error) string {
	var errno syscall.Errno
	if !errors.As(err, &errno) {
		return err.Error()
	}
	text := errno.Error()
	said := fmt.Sprintf("[Errno %d] %s%s", int(errno), strings.ToUpper(text[:1]), text[1:])
	var link *os.LinkError
	var path *os.PathError
	switch {
	case errors.As(err, &link):
		said += ": " + commandhelp.Quote(link.Old) + " -> " + commandhelp.Quote(link.New)
	case errors.As(err, &path):
		said += ": " + commandhelp.Quote(path.Path)
	}
	return said
}

func short(commit string) string {
	return commit[:min(12, len(commit))]
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
