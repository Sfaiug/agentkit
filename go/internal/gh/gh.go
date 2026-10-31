// Package gh is how ak asks GitHub, as Python's watch.gh_json asks it. It hides how ak runs gh:
// in a run's environment that may never prompt, from a folder that exists, on no input, for two
// minutes at most; and the reason it gives when gh fails: gh's own words, why it did not start,
// that it timed out, or that it printed no JSON.
package gh

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// ErrPython leaves the call to Python ak: Go cannot run gh, or say what it answered, as Python
// does.
var ErrPython = errors.New("left to Python")

const limit = 2 * time.Minute

// loggedOut is what gh says when the credentials are the problem rather than the network: its
// advice with no login at all, and the API's words for a rejected token. A 403 is not among
// them: GitHub answers one to perfectly good credentials that asked too often.
var loggedOut = regexp.MustCompile(`(?i)gh auth login|not logged in|bad credentials|HTTP 401`)

// LoggedOut is whether gh's reason is a login for the owner to fix.
func LoggedOut(why string) bool {
	return loggedOut.MatchString(why)
}

// JSON is the JSON value `gh args...` prints, run from dir, else from ak's checkout; or, where
// gh fails, why, in at most 300 characters.
func JSON(dir string, args ...string) (any, string, error) {
	env, err := config.ChildEnv()
	if err != nil {
		return nil, "", ErrPython
	}
	if info, err := os.Stat(dir); err != nil || !info.IsDir() {
		dir = config.Repo()
	}
	program, missing, err := find(dir)
	if program == "" {
		return nil, missing, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), limit)
	defer cancel()
	command := exec.CommandContext(ctx, program, args...)
	var stdout, stderr bytes.Buffer
	command.Dir, command.Stdout, command.Stderr = dir, &stdout, &stderr
	command.Env = append(env, "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1")
	command.WaitDelay = limit // a program gh left holding its output open is waited for no longer
	err = command.Run()
	var exited *exec.ExitError
	switch {
	case ctx.Err() != nil:
		return nil, "gh timed out", nil
	case err != nil && !errors.As(err, &exited), !utf8.Valid(stdout.Bytes()), !utf8.Valid(stderr.Bytes()):
		return nil, "", ErrPython
	}
	out := task.Text(stdout.Bytes())
	if err != nil {
		said := []rune(strings.TrimFunc(out+task.Text(stderr.Bytes()), config.Space))
		return nil, string(said[:min(len(said), 300)]), nil
	}
	value, err := run.Decode([]byte(out))
	if err != nil {
		return nil, "gh printed no JSON (" + err.Error() + ")", nil
	}
	return value, "", nil
}

// find is the gh Python's subprocess runs for a child working in dir: the first PATH entry, a
// relative one read from dir, holding an executable gh; else, where no entry holds one, why, as
// Python's OSError says it of 'gh'. An entry holding a gh Go cannot tell Python runs leaves the
// call to Python.
func find(dir string) (string, string, error) {
	path, set := os.LookupEnv("PATH")
	if !set {
		path = "/bin:/usr/bin" // Python's os.defpath
	}
	var errno syscall.Errno
	for _, entry := range strings.Split(path, string(os.PathListSeparator)) {
		candidate := filepath.Join(entry, "gh")
		if !filepath.IsAbs(candidate) {
			candidate, _ = filepath.Abs(filepath.Join(dir, candidate))
		}
		info, err := os.Stat(candidate)
		if err == nil && info.Mode().IsRegular() && info.Mode()&0o111 != 0 {
			return candidate, "", nil
		}
		// Python's exec goes on past a gh that is not there or under no folder, and says the last
		if !errors.As(err, &errno) || errno != syscall.ENOENT && errno != syscall.ENOTDIR {
			return "", "", ErrPython
		}
	}
	said := errno.Error()
	return "", fmt.Sprintf("gh: [Errno %d] %s%s: 'gh'", int(errno), strings.ToUpper(said[:1]), said[1:]), nil
}
