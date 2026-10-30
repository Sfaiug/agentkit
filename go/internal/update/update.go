// Package update is `ak update` where it moves nothing, as Python's agentkit/update.py says it: a
// dry run, and an update with no harness here and no ~/agentkit checkout.  Moving either is
// Python's.
package update

import (
	"bytes"
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// ErrPython leaves an update to Python ak before Go has written anything: one that would move a
// harness or ~/agentkit, or output Go cannot read as Python does.
var ErrPython = errors.New("left to Python")

// pins keep each harness from upgrading itself while it is asked its release.
var pins = []string{"DISABLE_AUTOUPDATER=1", "MUSE_NO_AUTO_UPDATE=1", "MUSE_LAUNCHER_INSTALL=0"}

// release is where Python's VERSION finds a release in a version command's output, its digits
// Unicode's; what VERSION takes after the number cannot change whether it finds one.
var release = regexp.MustCompile(`\p{Nd}+\.\p{Nd}+\.\p{Nd}+`)

// A plan is one harness `ak update` moves, as its manifest's `[update]` says.
type plan struct {
	name             string
	version, upgrade []string
	revert           bool
	cannot           string
}

// Main is `ak update` from the checkout at repo where Go carries it out, in Python's update.main
// order: what it prints, and its exit code or a refusal in Python's words.
func Main(repo string, dryRun bool, out, errOut io.Writer) (int, error) {
	live := filepath.Join(repo, "tests", "live.sh")
	if !regular(live) {
		return refuse(fmt.Errorf("no acceptance gate at %s; an unverified upgrade is not one", live))
	}
	plans, err := harnesses()
	if err == nil && len(plans) == 0 {
		err = errors.New("no configured harness says how it is upgraded; give one an [update] " +
			"version and upgrade command in its adapters/<name>.toml")
	}
	if err != nil {
		return refuse(err)
	}
	env, err := config.ChildEnv()
	if err != nil {
		return 0, ErrPython
	}
	env = append(env, pins...)
	before, absent := map[string]string{}, []string{}
	for _, each := range plans {
		if before[each.name], err = version(each, env); err != nil {
			return 0, err
		}
		if before[each.name] == "" && harness.Binary(each.version[0]) == "" {
			absent = append(absent, each.name)
		}
	}
	home, _ := os.UserHomeDir()
	checkout := filepath.Join(home, "agentkit")
	_, err = os.Stat(filepath.Join(checkout, ".git"))
	held := err == nil
	if !dryRun && (len(absent) < len(plans) || held) {
		return 0, ErrPython // a harness or ~/agentkit to move
	}
	agentkit := "update: agentkit: skipped: no checkout at " + checkout
	if held {
		said, err := agentkitVersion(env, checkout)
		if err != nil {
			return 0, err
		}
		agentkit = "update: agentkit " + cmp.Or(said, "?") +
			": would move forward (the next version swapped in + `install.sh`)"
	}
	if config.EnsureDirs() != nil {
		return 0, ErrPython
	}
	for _, name := range absent {
		fmt.Fprintf(out, "update: %s: skipped: not installed here\n", name)
	}
	if !dryRun {
		fmt.Fprintln(out, "update: no harness installed here; nothing to upgrade")
		fmt.Fprintln(out, agentkit)
		fmt.Fprintln(errOut, "update: nothing was upgraded; the gate was not run")
		return 1, nil
	}
	for _, each := range plans {
		note := "cannot be reverted: " + cmp.Or(each.cannot, "it offers no versioned reinstall")
		if each.revert {
			note = "versioned reinstall available"
		} else if harness.Snapshots(each.name) {
			note = "frozen installed release, not a reproducible versioned install; cannot be " +
				"reverted by its channel installer; requires a complete local snapshot for " +
				"rollback, checked before upgrading"
		}
		fmt.Fprintf(out, "%s %s (%s): %s\n", each.name, cmp.Or(before[each.name], "not installed"),
			note, commandhelp.ShellJoin(each.upgrade))
	}
	fmt.Fprintln(out, "update: dry run, nothing changed; each gate below says whether it would run")
	fmt.Fprintf(out, "update: gate live: run (`bash %s`)\n", live)
	fresh := filepath.Join(repo, "tests", "e2e-fresh.sh")
	platform := runtime.GOOS
	if platform == "windows" {
		platform = "win32" // as Python's sys.platform calls it
	}
	switch {
	case !regular(fresh):
		fmt.Fprintf(out, "update: gate fresh: skipped: no %s\n", fresh)
	case platform != "linux":
		fmt.Fprintf(out, "update: gate fresh: skipped: Linux only (this is %s)\n", platform)
	default:
		fmt.Fprintf(out, "update: gate fresh: run (`bash %s`)\n", fresh)
	}
	fmt.Fprintln(out, agentkit)
	return 0, nil
}

// refuse is a refusal once ak's own folders are made, as Python makes them first.
func refuse(err error) (int, error) {
	if errors.Is(err, ErrPython) || config.EnsureDirs() != nil {
		return 0, ErrPython
	}
	return 2, err
}

// harnesses is every configured harness whose manifest says how it is upgraded, in config.toml's
// order, as Python's update.harnesses reads them.
func harnesses() ([]plan, error) {
	names, err := config.Harnesses()
	if err != nil {
		return nil, err
	}
	var plans []plan
	for _, name := range names {
		facts, err := config.Section(name, "update")
		if err != nil {
			return nil, ErrPython // a manifest Go reads otherwise, in words that are not Python's
		}
		version, err := words(name, facts, "version")
		if err != nil {
			return nil, err
		}
		upgrade, err := words(name, facts, "upgrade")
		if err != nil {
			return nil, err
		}
		if version == nil || upgrade == nil {
			continue // nothing here knows how to move it
		}
		revert, err := words(name, facts, "revert")
		if err != nil {
			return nil, err
		}
		if _, err := words(name, facts, "latest"); err != nil {
			return nil, err
		}
		cannot, _ := facts["cannot"].(string)
		plans = append(plans, plan{name, version, upgrade, revert != nil, cannot})
	}
	return plans, nil
}

// words is one `[update]` command line out of a manifest, nil where it names none.
func words(name string, facts map[string]any, key string) ([]string, error) {
	list, ok := facts[key].([]any)
	if facts[key] == nil || ok && len(list) == 0 {
		return nil, nil
	}
	var argv []string
	for _, word := range list {
		word, valid := word.(string)
		ok = ok && valid && word != ""
		argv = append(argv, word)
	}
	if !ok {
		return nil, fmt.Errorf("adapters/%s.toml: [update].%s must be a list of words", name, key)
	}
	return argv, nil
}

// version is a harness's full release and build, as Python's update.version reads it: "" where
// its command fails or names no release.
func version(each plan, env []string) (string, error) {
	program := cmp.Or(harness.Binary(each.version[0]), each.version[0])
	stdout, stderr, ok := output(env, 2*time.Minute, append([]string{program}, each.version[1:]...)...)
	if !ok {
		return "", nil
	}
	if !utf8.Valid(stdout) || !utf8.Valid(stderr) {
		return "", ErrPython // Python puts its own replacement in for what is not UTF-8
	}
	var said []string
	for _, text := range [][]byte{stdout, stderr} {
		for _, line := range config.SplitLines(string(text)) {
			if line = strings.TrimFunc(line, config.Space); line != "" {
				said = append(said, line)
			}
		}
	}
	identity := strings.Join(said, "; ")
	if !release.MatchString(identity) {
		return "", nil
	}
	if identity, ok = harness.Identity(each.name, identity, each.version); !ok {
		return "", ErrPython
	}
	return identity, nil
}

// agentkitVersion is that checkout's short commit and its date, "" when git cannot say them.
func agentkitVersion(env []string, checkout string) (string, error) {
	stdout, _, ok := output(env, time.Minute, "git", "-C", checkout, "log", "-1", "--format=%h · %cs")
	if !ok {
		return "", nil
	}
	if !utf8.Valid(stdout) {
		return "", ErrPython // Python puts its own replacement in: its i18n.logOutputEncoding's bytes
	}
	return strings.TrimFunc(string(stdout), config.Space), nil
}

// output is what a command printed, as Python's subprocess.run captures it within a cap: its
// stdout and stderr, and whether it ran and exited 0 in time.
func output(env []string, limit time.Duration, argv ...string) (stdout, stderr []byte, ok bool) {
	ctx, cancel := context.WithTimeout(context.Background(), limit)
	defer cancel()
	command := exec.CommandContext(ctx, argv[0], argv[1:]...)
	if errors.Is(command.Err, exec.ErrDot) {
		command.Err = nil // Python's subprocess runs what a relative PATH entry finds
	}
	var out, errOut bytes.Buffer
	command.Env, command.Stdin, command.Stdout, command.Stderr = env, os.Stdin, &out, &errOut
	// a program it left holding its output open is waited for no longer than the cap
	command.WaitDelay = limit
	err := command.Run()
	return out.Bytes(), errOut.Bytes(), err == nil
}

func regular(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}
