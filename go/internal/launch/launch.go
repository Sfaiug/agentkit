// Package launch starts a run from a task file as Python ak's `ak run <task.md>` does, up to
// its loop: the run's id and directory, the task's copy, the receipt, the gate's admission,
// preflight, and how a refused launch ends.  It hides which launches Go makes today: one on a
// path of Python's launch that Go has, which preflight refuses.  Any other it leaves to Python
// (ErrPython), deciding so before it writes anything, so preflight is settled first.
package launch

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"maps"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
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
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// ErrPython is a launch Go leaves to Python ak.
var ErrPython = errors.New("a launch Go leaves to Python ak")

// ErrStopped is a launch a stop ended as its title was saved, its line said on out as Python
// says it where the stop lands in its preflight.
var ErrStopped = errors.New("a launch a stop ended")

// Values and Switches are a launch's options, in the order Python's launch_opts records them.
var (
	Values   = []string{"--rounds", "--exec", "--review", "--review-pr", "--parallel"}
	Switches = []string{"--no-worktree", "--no-merge", "--bg", "--anyway", "--first"}
)

var (
	unslug = regexp.MustCompile(`[^a-z0-9]+`)
	// a git that refused to prompt, which Python's git stops on in its own words
	prompted = regexp.MustCompile(`(?i)terminal prompts disabled|could not read (?:Username|Password)|prompts (?:are )?disabled|askpass`)
)

// Task launches the task file at the absolute path with the options given, saying on out what
// the run's log says, and returns why the launch is refused.
func Task(path string, values map[string]string, flags map[string]bool, out io.Writer) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil || !utf8.Valid(data) {
		return "", ErrPython
	}
	text := task.Text(data)
	meta, cmds, err := task.Read(path)
	bound, unbound := config.Bind()
	if err != nil || unbound != nil || python(path, values, flags, bound) {
		return "", ErrPython
	}
	stem := filepath.Base(path)
	if dot := strings.LastIndexByte(stem, '.'); 0 < dot && dot < len(stem)-1 {
		stem = stem[:dot]
	}
	id := time.Now().Format("20060102-1504-") + slug(task.Title(text, stem))
	dir := filepath.Join(run.Runs(), id)
	taken, err := exists(dir)
	for n := 2; taken && err == nil; n++ {
		dir = filepath.Join(run.Runs(), id+"-"+strconv.Itoa(n))
		taken, err = exists(dir)
	}
	if err != nil {
		return "", err
	}
	copied := filepath.Join(dir, "task.md")
	reason, warning, err := preflight(meta, cmds, path, copied, flags)
	if err != nil {
		return "", err
	}
	// a reader that stops reading ends the reading, never the launch: a line to a closed
	// stdout goes nowhere, as Python's say has it, where Go's runtime would die of SIGPIPE
	signal.Notify(make(chan os.Signal, 1), syscall.SIGPIPE)
	logged := filepath.Join(dir, "log.txt")
	log := func(message string) error {
		line := time.Now().Format("[15:04:05] ") + message + "\n"
		io.WriteString(out, line)
		file, err := os.OpenFile(logged, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
		if err != nil {
			return err
		}
		_, err = file.WriteString(line)
		return cmp.Or(err, file.Close())
	}
	title := task.Title(text, "task")
	var ended *run.Object // the record as the refusal leaves it
	for _, step := range []func() error{
		config.EnsureDirs,
		func() error { return os.Mkdir(dir, 0o777) },
		func() error { return os.WriteFile(copied, []byte(text), 0o666) },
		func() error { return os.WriteFile(logged, nil, 0o666) },
		func() error { return receive(dir, path, values, flags, bound) },
		func() error {
			return run.Change(dir, func(record *run.Object) error {
				if record.Str("state") == "stopped" {
					io.WriteString(out, "stopped "+filepath.Base(dir)+"\n")
					return ErrStopped
				}
				record.Set("title", title)
				return nil
			})
		},
		func() error {
			if warning == "" {
				return nil
			}
			return log(warning)
		},
		func() error {
			return run.Change(dir, func(record *run.Object) error {
				// a stop that landed first stands, as Python's mark_state leaves it
				if record.Str("state") != "stopped" {
					set(record, "state", "error", "finished_at", now(), "error", reason)
				}
				ended = record
				return nil
			})
		},
	} {
		if err := step(); err != nil {
			return "", err
		}
	}
	delivery, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return "", err
	}
	why := ended.Str("error")
	result := fmt.Sprintf("# FAIL — %s\n\nVERDICT: %s\n\n## Why this run stopped\n\n%s\n\nrelaunch: ak run %s\n\n",
		cmp.Or(ended.Str("title"), filepath.Base(dir)), cmp.Or(ended.Str("verdict"), "none"),
		cmp.Or(why, "no reason was recorded"), copied)
	err = os.WriteFile(filepath.Join(dir, "result.md"), []byte(result), 0o666)
	delivery.Close()
	if err != nil || why == "" {
		return reason, nil // a result Python cannot write, or a stop's, goes untold
	}
	return reason, log("ERROR " + why)
}

// python is whether Python ak makes this launch otherwise than Go would, or reads what Go
// cannot read as it does: a pull request's review, a queued run's start, a seat's launch, one
// that history records, one the gate does not admit outright, one Python's rival check may
// refuse, a config Python refuses before its run, a test rig's adapters, a home HOME does not
// name, or a string for the record Python would write with a lone surrogate.
func python(path string, values map[string]string, flags map[string]bool, bound config.Binding) bool {
	depth, known := runDepth()
	_, capped := config.MaxRuns()
	_, review := values["--review-pr"]
	if review || os.Getenv("AGENTKIT_RUN_DIR") != "" || os.Getenv("AGENTKIT_SESSION") != "" || sink() == "" ||
		os.Getenv("AGENTKIT_ADAPTER_DIR") != "" || os.Getenv("HOME") == "" ||
		!known || os.Getenv("AK_MAX_RUNS") != "0" && depth == 0 || capped != nil || config.RunMemoryRefused() ||
		len(bound.Workers) == 0 ||
		!readable(path, run.Runs(), os.Getenv("AK_PARENT_RUN"), os.Getenv("AK_NOTIFY_SINK")) ||
		!readable(slices.Collect(maps.Values(values))...) {
		return true
	}
	if flags["--anyway"] {
		return false
	}
	for _, dir := range run.Dirs() {
		if record, err := run.Read(dir); errors.Is(err, run.ErrLoneSurrogate) || record != nil && run.Active(record) {
			return true
		}
	}
	return false
}

// readable is whether every text is UTF-8, as Go reads back what it writes: Python writes a
// byte that is none as a lone surrogate.
func readable(texts ...string) bool {
	return !slices.ContainsFunc(texts, func(text string) bool { return !utf8.ValidString(text) })
}

// runDepth is the depth AK_RUN_DEPTH gives, as Python's run_depth reads it, and whether Go
// reads it so.
func runDepth() (int, bool) {
	value := cmp.Or(os.Getenv("AK_RUN_DEPTH"), "0")
	if strings.Trim(value, "0123456789") != "" {
		return 0, false
	}
	depth, err := strconv.Atoi(value)
	return depth, err == nil
}

// preflight is why Python's preflight refuses the task, run from its copy, and the warning its
// log says first: a repository that is no git repository, a base git cannot read, more than 3
// checks a round runs, or a `from:` the run cannot start from.  It leaves to Python a task it
// passes and a run that would land.
func preflight(meta map[string]string, cmds []string, path, copied string, flags map[string]bool) (string, string, error) {
	repo := ""
	switch named := meta["repo"]; {
	case strings.ToLower(named) == "none":
	case named != "":
		if account, _, _ := strings.Cut(named, "/"); account != "~" && strings.HasPrefix(account, "~") {
			return "", "", ErrPython // a `~user`: that account's home is Python's to find
		}
		repo = config.Absolute(named)
		if !readable(repo) {
			return "", "", ErrPython
		}
		found, err := exists(filepath.Join(repo, ".git"))
		if err != nil || !found {
			return fmt.Sprintf("%s: repo %s is not a git repository", copied, repo), "", err
		}
	default:
		top, _, found, err := git("", "rev-parse", "--show-toplevel")
		tasks := config.Resolve(filepath.Join(config.Home(), "tasks")) + string(filepath.Separator)
		if rest, filed := strings.CutPrefix(path, tasks); err != nil || !found && filed && strings.ContainsRune(rest, filepath.Separator) {
			return "", "", ErrPython // the checkout a task folder is named for is Python's to find
		}
		if found {
			repo = config.Resolve(top)
		}
		if !readable(repo) {
			return "", "", ErrPython
		}
	}
	if repo != "" && !flags["--no-merge"] {
		return "", "", ErrPython
	}
	// what Python refuses after the base, settled first: finding the base may write origin/HEAD
	var every []string
	for _, cmd := range cmds {
		cmd, _ = task.SplitOnce(cmd)
		if _, once := task.SplitOnce(cmd); !once {
			every = append(every, cmd)
		}
	}
	later := task.ChecksRefusal(every)
	switch from := meta["from"]; {
	case later != "" || from == "":
	case repo == "":
		later = copied + ": from: needs a repository; a scratch run has no branch to start from"
	case flags["--no-worktree"]:
		later = copied + ": from: needs a worktree; drop --no-worktree so the run gets its own checkout"
	default:
		branch, _, _, err := git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/"+from)
		if err != nil {
			return "", "", err
		}
		if branch == "" {
			later = fmt.Sprintf("%s: from: %s is not a local branch", copied, commandhelp.Quote(from))
		}
	}
	if repo != "" && meta["base"] == "" {
		reason, warning, err := defaultBase(repo, later != "")
		if reason != "" || err != nil {
			return reason, "", err
		}
		if later != "" {
			return later, warning, nil
		}
	}
	if later == "" {
		return "", "", ErrPython
	}
	return later, "", nil
}

// defaultBase is why Python's default_base cannot name the repository's default branch, or "",
// and the warning its log says where it falls back to the current branch.  Asking origin for
// its HEAD writes origin/HEAD where a branch of origin's is tracked, so only a launch already
// refused asks then; any other is Python's.
func defaultBase(repo string, refused bool) (string, string, error) {
	ask := []string{"symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"}
	if head, _, _, err := git(repo, ask...); err != nil || head != "" {
		return "", "", err
	}
	if tracked, _, _, err := git(repo, "for-each-ref", "--count=1", "refs/remotes/origin/"); err != nil || tracked != "" && !refused {
		return "", "", cmp.Or(err, ErrPython)
	}
	// a clone made before origin had a HEAD: asked once
	if _, _, _, err := git(repo, "remote", "set-head", "origin", "--auto"); err != nil {
		return "", "", err
	}
	if head, _, _, err := git(repo, ask...); err != nil || head != "" {
		return "", "", err
	}
	current, why, ok, err := git(repo, "rev-parse", "--abbrev-ref", "HEAD")
	if err != nil || !ok {
		return fmt.Sprintf("git rev-parse --abbrev-ref HEAD failed in %s: %s", repo, why), "", err
	}
	return "", fmt.Sprintf("WARN %s has no origin/HEAD; basing this run on the current branch %s", repo, current), nil
}

// git is git's stdout and stderr in repo ("" the current directory), stripped, and whether it
// exited 0, as Python's tool_run reads them; ErrPython where Python says what happened in its
// own words: a git that never answered or refused to prompt.  Bytes that are no UTF-8 decode
// as Python's do, so what a git that wrote said, set-head's included, is still read.
func git(repo string, args ...string) (string, string, bool, error) {
	if repo != "" {
		args = append([]string{"-C", repo}, args...)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, "git", args...)
	command.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0", "GH_PROMPT_DISABLED=1")
	var stdout, stderr strings.Builder
	command.Stdout, command.Stderr = &stdout, &stderr
	err := command.Run()
	var exit *exec.ExitError
	said := replaced(stderr.String())
	if ctx.Err() != nil || err != nil && (!errors.As(err, &exit) || prompted.MatchString(said)) {
		return "", "", false, ErrPython
	}
	strip := func(text string) string { return strings.TrimFunc(task.Text([]byte(text)), config.Space) }
	return strip(replaced(stdout.String())), strip(said), err == nil, nil
}

// replaced is text as Python decodes it with errors="replace": one U+FFFD for each byte that
// starts no character, and for each longest start of one that never finishes.
func replaced(text string) string {
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

// receive writes the launch's receipt, its first record, as Python's capture_launch writes it
// under the slots lock, with the gate's outright admission.
func receive(dir, path string, values map[string]string, flags map[string]bool, bound config.Binding) error {
	slots, err := lock.Wait(context.Background(), filepath.Join(run.Runs(), ".slots.lock"))
	if err != nil {
		return err
	}
	defer slots.Close()
	depth, _ := runDepth()
	var parent, identity any
	if value, set := os.LookupEnv("AK_PARENT_RUN"); set {
		parent = value
	}
	if born, ok := host.ReadIdentity(os.Getpid()); ok {
		identity = set(run.NewObject(), "boot", born.Boot, "ticks", int(born.Ticks), "started_at", born.StartedAt)
	}
	launched, efforts := run.NewObject(), run.NewObject()
	for _, flag := range Values {
		set(launched, flag, nil)
		if value, given := values[flag]; given {
			set(launched, flag, value)
		}
	}
	for _, flag := range Switches {
		set(launched, flag, flags[flag])
	}
	receipt := []any{"run_id", filepath.Base(dir), "state", "running", "verdict", nil,
		"launched_session", nil, "started_at", now(), "queued_at", now(), "slot_waiting", false,
		"run_depth", depth, "parent_run", parent, "reservation_pending", true,
		"unattended", os.Getenv("AGENTKIT_UNATTENDED") != "", "pid", os.Getpid(),
		"process_identity", identity, "launch_opts", launched}
	if bound.Reviewers != nil {
		receipt = append(receipt, "workers", bound.Workers, "reviewers", bound.Reviewers)
	}
	for _, model := range bound.Models {
		keys := run.NewObject()
		for _, effort := range bound.Efforts[model] {
			set(keys, effort[0], effort[1])
		}
		set(efforts, model, keys)
	}
	receipt = append(receipt, "efforts", efforts, "review_pr", nil, "reported", false, "base_proof", "owed",
		"notify_sink", sink(), "task_file", path)
	if flags["--first"] {
		receipt = append(receipt, "first", true)
	}
	return run.Create(dir, set(run.NewObject(), append(receipt, "slot_started_at", now())...))
}

// slug is Python's slugify: Python lowers İ to i and a combining dot, Go to i alone.
func slug(title string) string {
	slug := unslug.ReplaceAllString(strings.ToLower(strings.ReplaceAll(title, "İ", "i̇")), "-")
	slug = strings.Trim(slug, "-")
	return cmp.Or(strings.Trim(slug[:min(len(slug), 40)], "-"), "task")
}

// sink is the notify sink a launch is under, which keeps it out of history.
func sink() string { return strings.TrimFunc(os.Getenv("AK_NOTIFY_SINK"), config.Space) }

func now() float64 { return float64(time.Now().UnixNano()) / 1e9 }

// exists is Python's Path.exists: false where the path is missing, under a file or in a link
// loop, and ErrPython for any other error, which Python raises in its runtime's own words.
func exists(path string) (bool, error) {
	_, err := os.Stat(path)
	var errno syscall.Errno
	if err == nil || errors.As(err, &errno) && slices.Contains([]syscall.Errno{syscall.ENOENT, syscall.ENOTDIR, syscall.EBADF, syscall.ELOOP}, errno) {
		return err == nil, nil
	}
	return false, ErrPython
}

// set sets each key and value of pairs on the record in turn.
func set(record *run.Object, pairs ...any) *run.Object {
	for i := 0; i < len(pairs); i += 2 {
		record.Set(pairs[i].(string), pairs[i+1])
	}
	return record
}
