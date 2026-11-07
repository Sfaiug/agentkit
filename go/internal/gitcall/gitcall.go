// Package gitcall is git as Python's gitcall runs it for a run: in tool_env, with every prompt
// off, capped, and decoded as Python decodes it.  A git that ran out of time or was refused its
// prompt is a Stopped, never an answer: nothing was learned, so nothing can be decided on it.
package gitcall

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
	"agentkit/internal/lock"
	"agentkit/internal/task"
)

// Junk is what a test run, a build or an editor drops next to the work.
var Junk = []string{"__pycache__/", "*.pyc", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", "node_modules/", ".DS_Store", "*.swp"}

// Making is the reason ak locks a checkout it makes while git makes it, so a maker killed before
// it unlocks leaves one gc knows holds nothing yet.
const Making = "ak is making this checkout"

// ScratchMark, a file in a detached checkout's own git directory, says a lander made it to check
// a commit in, so gc may take it.
const ScratchMark = "ak-lander-scratch"

// Stamp is ak's own temporary commits' author and date, Python's STAMP: identical trees and
// parents give every attempt the same commit.
var Stamp = []string{"GIT_AUTHOR_NAME=ak", "GIT_AUTHOR_EMAIL=ak@localhost", "GIT_COMMITTER_NAME=ak",
	"GIT_COMMITTER_EMAIL=ak@localhost", "GIT_AUTHOR_DATE=2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE=2000-01-01T00:00:00Z"}

// CapSeconds is how many seconds a git may take, Python's TOOL_CAP.
const CapSeconds = 120

// grace is what a git out of time gets between SIGTERM and SIGKILL: on SIGTERM it removes its
// index and ref locks and exits, where SIGKILL leaves them for the next git to fail on.
const grace = 5 * time.Second

// timedOut is the exit Run says a git that never answered ended with.
const timedOut = -1 << 16

var (
	// what git says when the prompt it wanted was refused
	prompted = regexp.MustCompile(`(?i)terminal prompts disabled|could not read (?:Username|Password)|prompts (?:are )?disabled|askpass`)
	// the line a fetch prints for a ref another process holds
	refLocked = regexp.MustCompile(`^error: cannot lock ref '.*': (?:is at \w+ but expected \w+|Unable to create '.*': File exists\.)$`)
)

// A Stopped is a git out of time, or refused the prompt it wanted.
type Stopped struct{ Why string }

func (s *Stopped) Error() string { return s.Why }

// A Git runs git in Repo ("" the current directory).  Env changes its environment: `KEY=value`
// sets, a bare `KEY` drops.  Cap is its limit, CapSeconds where none.  Ctx, where set, stops it
// as its limit does, and a git it stopped answers with its cause: work dropped mid-way waits on
// no git of its own.  In, where set, is what it reads.
type Git struct {
	Repo string
	Env  []string
	Cap  time.Duration
	Ctx  context.Context
	In   []byte
}

// environment is Python's tool_env as Env changes it: no seat's name, and no prompt.
func (g Git) environment() ([]string, error) {
	child, err := config.ChildEnv()
	if err != nil {
		return nil, err
	}
	var env []string
	for _, pair := range child {
		if !strings.HasPrefix(pair, "AGENTKIT_SESSION=") {
			env = append(env, pair)
		}
	}
	env = append(env, "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1")
	for _, change := range g.Env {
		if strings.Contains(change, "=") {
			env = append(env, change)
			continue
		}
		var kept []string
		for _, pair := range env {
			if !strings.HasPrefix(pair, change+"=") {
				kept = append(kept, pair)
			}
		}
		env = kept
	}
	return env, nil
}

// Bytes is one git as it ended: its exit, timedOut for one past its limit, and what it wrote.
func (g Git) Bytes(args ...string) (int, []byte, []byte, error) {
	env, err := g.environment()
	if err != nil {
		return 0, nil, nil, err
	}
	limit := g.Cap
	if limit <= 0 {
		limit = CapSeconds * time.Second
	}
	if g.Repo != "" {
		args = append([]string{"-C", g.Repo}, args...)
	}
	within := g.Ctx
	if within == nil {
		within = context.Background()
	}
	ctx, cancel := context.WithTimeout(within, limit)
	defer cancel()
	command := exec.CommandContext(ctx, "git", args...)
	command.Cancel = func() error { return command.Process.Signal(syscall.SIGTERM) }
	command.WaitDelay = grace
	command.Env = env
	if g.In != nil {
		command.Stdin = bytes.NewReader(g.In)
	}
	var stdout, stderr bytes.Buffer
	command.Stdout, command.Stderr = &stdout, &stderr
	err = command.Run()
	var exit *exec.ExitError
	switch {
	case within.Err() != nil:
		return 0, nil, nil, context.Cause(within)
	case ctx.Err() != nil:
		return timedOut, stdout.Bytes(), stderr.Bytes(), nil
	case errors.As(err, &exit):
		return exit.ExitCode(), stdout.Bytes(), stderr.Bytes(), nil
	}
	return 0, stdout.Bytes(), stderr.Bytes(), err
}

// retried is whether Python's tool_run gives a git out of time its one retry: repeating anything
// else can turn a timeout into an "already in progress" failure.
func retried(args []string) bool {
	return len(args) > 0 && (args[0] == "fetch" || args[0] == "push" || args[0] == "ls-remote")
}

// Run is Python's tool_run: its exit and what it wrote, decoded.
func (g Git) Run(args ...string) (int, string, string, error) {
	code, stdout, stderr, err := g.Bytes(args...)
	if err == nil && code == timedOut && retried(args) {
		time.Sleep(time.Second)
		code, stdout, stderr, err = g.Bytes(args...)
	}
	if err != nil {
		return 0, "", "", err
	}
	if code == timedOut {
		return code, "", fmt.Sprintf("`git %s` was killed after its limit: the remote did not answer", args[0]), nil
	}
	return code, task.Text([]byte(Decoded(string(stdout)))), task.Text([]byte(Decoded(string(stderr)))), nil
}

// Halted is whether a call that ended so stopped rather than answered, Python's stopped.
func Halted(code int, text string) bool {
	return code == timedOut || code != 0 && prompted.MatchString(text)
}

// Strip is text as Python's str.strip leaves it.
func Strip(text string) string { return strings.TrimFunc(text, config.Space) }

// Must is what git printed, stripped, its failure an error, Python's git.
func (g Git) Must(args ...string) (string, error) {
	return g.answer(true, args)
}

// Try is Python's git with check off: a git that said no is an empty answer, one that never
// answered is a Stopped.
func (g Git) Try(args ...string) (string, error) {
	return g.answer(false, args)
}

func (g Git) answer(check bool, args []string) (string, error) {
	code, out, said, err := g.Run(args...)
	if err != nil {
		return "", err
	}
	stop := Halted(code, said)
	if (check || stop) && code != 0 {
		why := fmt.Sprintf("git %s failed in %s: %s", strings.Join(args, " "), g.Repo, Strip(said))
		if stop {
			return "", &Stopped{why}
		}
		return "", errors.New(why)
	}
	return Strip(out), nil
}

// Out is its exit and all it wrote, stripped, for a step whose failure is a result to report,
// Python's git_out: a stop is never a result.
func (g Git) Out(args ...string) (int, string, error) {
	code, out, said, err := g.Run(args...)
	if err != nil {
		return 0, "", err
	}
	if Halted(code, said) {
		return 0, "", &Stopped{fmt.Sprintf("git %s stopped in %s: %s", strings.Join(args, " "), g.Repo, Strip(out+said))}
	}
	return code, Strip(out + said), nil
}

// Fetch is `git fetch` as Out answers it, Python's fetch: every run's worktree shares one
// repository's refs, so a fetch that lost the race for a ref goes again at once, until it goes
// through or its limit, counted from its first try, is spent.
func (g Git) Fetch(args ...string) (int, string, error) {
	// Git's connectivity check enumerates local refs: deleting one mid-read can turn it
	// into a "bad object". Share preparation's directory lock; cleanup takes it exclusively.
	common, err := g.Must("rev-parse", "--path-format=absolute", "--git-common-dir")
	if err != nil {
		return 0, "", err
	}
	held, err := lock.Shared(common)
	if err != nil {
		return 0, "", err
	}
	defer held.Close()
	deadline := time.Now().Add(CapSeconds * time.Second)
	args = append([]string{"fetch"}, args...)
	code, out, err := g.Out(args...)
	for err == nil && code != 0 && time.Now().Before(deadline) && refHeld(out) {
		left := g
		left.Cap = time.Until(deadline)
		code, out, err = left.Out(args...)
		var stopped *Stopped
		if errors.As(err, &stopped) && !time.Now().Before(deadline) {
			return code, out, nil // the limit ran out mid-try: the lock it kept losing is the answer
		}
	}
	return code, out, err
}

// refHeld is whether a failed fetch failed only on refs another process holds: a ref no retry
// can write fails it at once.
func refHeld(out string) bool {
	failed := 0
	for _, line := range config.SplitLines(out) {
		bang := strings.HasPrefix(strings.TrimFunc(line, config.Space), "!") && !strings.HasSuffix(line, "(unable to update local ref)")
		if strings.HasPrefix(line, "error:") || strings.HasPrefix(line, "fatal:") || bang {
			if !refLocked.MatchString(line) {
				return false
			}
			failed++
		}
	}
	return failed > 0
}

// DefaultBase is the branch origin calls default, Python's default_base, and the warning its log
// says where it falls back to the current branch.  A clone made before origin had a HEAD asks
// origin once, which writes origin/HEAD.
func DefaultBase(repo string) (string, string, error) {
	g := Git{Repo: repo}
	for attempt := 1; attempt <= 2; attempt++ {
		head, err := g.Try("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
		if err != nil || head != "" {
			return head, "", err
		}
		if attempt == 1 {
			if _, err := g.Try("remote", "set-head", "origin", "--auto"); err != nil {
				return "", "", err
			}
		}
	}
	current, err := g.Must("rev-parse", "--abbrev-ref", "HEAD")
	if err != nil {
		return "", "", err
	}
	return current, fmt.Sprintf("WARN %s has no origin/HEAD; basing this run on the current branch %s", repo, current), nil
}

// OwnerName is `owner/name`, lowercase, of a clone's URL or path, Python's owner_name: a GitHub
// slug, and a local origin's last two parts.
func OwnerName(url string) string {
	parts := strings.Split(strings.ReplaceAll(strings.TrimSuffix(strings.TrimRight(url, "/"), ".git"), ":", "/"), "/")
	return strings.ToLower(strings.Join(parts[max(0, len(parts)-2):], "/"))
}

// ProjectEnv is what git's environment changes to work on the checkout at repo and nothing else,
// Python's project_env: GIT_DIR names its own `.git`, so git looks nowhere else, and the other
// variables git keeps for one repository are dropped.
func ProjectEnv(repo string) []string {
	var env []string
	if code, out, _, err := (Git{}).Run("rev-parse", "--local-env-vars"); err == nil && code == 0 {
		env = strings.Fields(out)
	}
	return append(env, "GIT_DIR="+filepath.Join(config.Absolute(repo), ".git"))
}

// AgentsBody is the body of the AGENTS.md committed at ref in repo, front matter removed: read
// from git, never a checkout's file, as the rules are what was merged.  "" where there is none,
// where it is a link, or where it cannot be read.
func AgentsBody(repo, ref string) string {
	g := Git{Repo: repo, Env: ProjectEnv(repo)}
	listed, err := g.Try("ls-tree", ref, "--", "AGENTS.md")
	fields := strings.Fields(listed)
	if err != nil || len(fields) < 3 || !strings.HasPrefix(fields[0], "100") {
		return ""
	}
	text, err := g.Try("cat-file", "blob", fields[2])
	if err != nil {
		return ""
	}
	return Strip(task.WithoutFront(text))
}

// DeclaredAt is a key's value in the front matter of AGENTS.md at ref, "" for none: a read that
// fails or runs slow is no declaration.
func DeclaredAt(repo, ref, key string, env ...string) string {
	value, _ := declaredAt(repo, ref, key, env)
	return value
}

// Declared is a key's value in the front matter of the checkout's AGENTS.md as written.
func Declared(checkout, key string) string {
	data, err := os.ReadFile(filepath.Join(checkout, "AGENTS.md"))
	if err != nil {
		return ""
	}
	return task.FrontValue(task.Text([]byte(Decoded(string(data)))), key)
}

// Decoded is text as Python decodes it with errors="replace": one U+FFFD for each byte that
// starts no character, and for each longest start of one that never finishes.
func Decoded(text string) string {
	var decoded strings.Builder
	for len(text) > 0 {
		r, n := utf8.DecodeRuneInString(text)
		if r != utf8.RuneError || n > 1 {
			decoded.WriteString(text[:n])
			text = text[n:]
			continue
		}
		// the bytes UTF-8 lets follow the lead byte, the second of them narrowed by some leads
		lo, hi, want := byte(0x80), byte(0xBF), 0
		switch lead := text[0]; {
		case lead >= 0xC2 && lead <= 0xDF:
			want = 1
		case lead == 0xE0:
			lo, want = 0xA0, 2
		case lead == 0xED:
			hi, want = 0x9F, 2
		case lead >= 0xE1 && lead <= 0xEF:
			want = 2
		case lead == 0xF0:
			lo, want = 0x90, 3
		case lead == 0xF4:
			hi, want = 0x8F, 3
		case lead >= 0xF1 && lead <= 0xF3:
			want = 3
		}
		for n <= want && n < len(text) && lo <= text[n] && text[n] <= hi {
			n, lo, hi = n+1, 0x80, 0xBF
		}
		decoded.WriteRune(utf8.RuneError)
		text = text[n:]
	}
	return decoded.String()
}
