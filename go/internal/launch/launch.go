// Package launch starts a run from a task file as Python ak's `ak run <task.md>` does, up to
// its loop: the run's id and directory, the task's copy, the receipt, the gate's admission,
// preflight, and how a refused launch ends.  It hides which launches Go makes today: one on a
// path of Python's launch that Go has, which preflight refuses or whose run preflight passes, a
// scratch task's or a repository's with --no-merge or --no-worktree, a review of somebody else's
// pull request from no seat, or of a seat's own with --no-merge, and that run goes on in package loop.  A seat's launch it judges as
// Python's run.parse does, and one that passes is the seat's run: its receipt names the seat and
// binds the seat's lists and efforts, and the seat's bar and project follow it (seat.go).  Any
// other it leaves to Python (ErrPython), deciding so before it writes anything, so preflight is
// settled first.
package launch

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"maps"
	"os"
	"os/signal"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/helper"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/task"
)

// ErrPython is a launch Go leaves to Python ak.
var ErrPython = errors.New("a launch Go leaves to Python ak")

// ErrStopped is a launch a stop ended as its title was saved, its line said on out as Python
// says it where the stop lands in its preflight.
var ErrStopped = errors.New("a launch a stop ended")

// Values and Switches are a launch's options, in the order Python's launch_opts records them.
var (
	Values   = run.LaunchValues
	Switches = run.LaunchSwitches
)

// Task launches the task file at the absolute path with the options given, saying on out what
// the run's log says and on errOut what becomes of a run its driver left: `ak run`'s exit status,
// and why the launch is refused, "" for a run that went on.
func Task(path string, values map[string]string, flags map[string]bool, out, errOut io.Writer) (int, string, error) {
	data, err := os.ReadFile(path)
	if err != nil || !utf8.Valid(data) {
		return 0, "", ErrPython
	}
	text := task.Text(data)
	meta, cmds, err := task.Read(path)
	bound, unbound := bind()
	if err != nil || unbound != nil || python(path, values, bound) {
		return 0, "", ErrPython
	}
	// read before the receipt, as Python's capture_launch does: a refusal here leaves no run
	if _, err := config.MaxRuns(); err != nil {
		return 2, err.Error(), nil
	}
	stem := filepath.Base(path)
	if dot := strings.LastIndexByte(stem, '.'); 0 < dot && dot < len(stem)-1 {
		stem = stem[:dot]
	}
	named := task.Title(text, stem)
	dir, err := freeDir(time.Now().Format("20060102-1504-") + task.Slug(named))
	if err != nil {
		return 0, "", err
	}
	copied := filepath.Join(dir, "task.md")
	reason, warning, place, err := preflight(meta, cmds, path, copied, named, values, flags, bound)
	var outright *refusedOutright
	if errors.As(err, &outright) {
		return 2, outright.why, nil
	}
	seated, _, _ := Seat()
	// a seat's launch a rule refuses is said where the seat typed it, which is Python's yet
	if err == nil && reason != "" && seated != "" {
		err = ErrPython
	}
	if err != nil {
		return 0, "", err
	}
	log, unstopped := logger(dir, out), guarded(dir, out)
	logged := filepath.Join(dir, "log.txt")
	title := task.Title(text, "task")
	for _, step := range []func() error{
		config.EnsureDirs,
		func() error { return os.Mkdir(dir, 0o777) },
		func() error { return os.WriteFile(copied, []byte(text), 0o666) },
		func() error { return os.WriteFile(logged, nil, 0o666) },
		func() error { return receive(dir, path, values, flags, bound, seated) },
		func() error { seat.Redress(seated); return nil }, // the seat's bar says it from the start
		func() error { return unstopped(func(record *run.Object) { record.Set("title", title) }) },
	} {
		if err := step(); err != nil {
			return 0, "", err
		}
	}
	if reason == "" {
		code, err := drive(dir, meta, place, warning, flags, seated, unstopped, log, out, errOut)
		return code, "", err
	}
	return refuse(dir, reason, warning, log)
}

// freeDir is the run's directory under that id, `-N` after it where the id is taken.
func freeDir(id string) (string, error) {
	dir := filepath.Join(run.Runs(), id)
	taken, err := exists(dir)
	for n := 2; taken && err == nil; n++ {
		dir = filepath.Join(run.Runs(), id+"-"+strconv.Itoa(n))
		taken, err = exists(dir)
	}
	return dir, err
}

// logger says a line on out and in the run's log.  A reader that stops reading ends the reading,
// never the launch: a line to a closed stdout goes nowhere, as Python's say has it, where Go's
// runtime would die of SIGPIPE.
func logger(dir string, out io.Writer) func(string) error {
	signal.Notify(make(chan os.Signal, 1), syscall.SIGPIPE)
	return func(message string) error {
		line := time.Now().Format("[15:04:05] ") + message + "\n"
		io.WriteString(out, line)
		file, err := os.OpenFile(filepath.Join(dir, "log.txt"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
		if err != nil {
			return err
		}
		_, err = file.WriteString(line)
		return cmp.Or(err, file.Close())
	}
}

// guarded changes the record unless a stop landed, which it says on out.
func guarded(dir string, out io.Writer) func(func(*run.Object)) error {
	return func(change func(*run.Object)) error {
		return run.Change(dir, func(record *run.Object) error {
			if record.Str("state") == "stopped" {
				io.WriteString(out, "stopped "+filepath.Base(dir)+"\n")
				return ErrStopped
			}
			change(record)
			return nil
		})
	}
}

// refuse ends a launch its receipt already records, as a run in error.
func refuse(dir, reason, warning string, log func(string) error) (int, string, error) {
	var ended *run.Object // the record as the refusal leaves it
	for _, step := range []func() error{
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
					// and this launch started nothing to sweep, so nothing reaps it
					run.SetAll(record, "state", "error", "finished_at", now(), "error", reason,
						"tree_stopped", []any{record.Get("pid"), record.Get("process_identity")})
				}
				ended = record
				return nil
			})
		},
	} {
		if err := step(); err != nil {
			return 0, "", err
		}
	}
	why := ended.Str("error")
	if err := run.Report(dir, ended); err != nil || why == "" {
		return 2, reason, nil // a result Python cannot write, or a stop's, goes untold
	}
	return 2, reason, log("ERROR " + why)
}

// python is whether Python ak makes this launch otherwise than Go would, or reads what Go
// cannot read as it does: any that leaves unread surroundings to Python, one naming no executor,
// a seat's whose runs Go cannot count its project from, or a string for the record Python would
// write with a lone surrogate.  A count that is none the gate never reads: Task refuses it.
func python(path string, values map[string]string, bound config.Binding) bool {
	name, _, unnamed := Seat()
	return unnamed != nil || unread() || len(bound.Workers) == 0 || !readable(path) ||
		!readable(slices.Collect(maps.Values(values))...) || name != "" && !seat.Votes(name)
}

// elsewhere is whether this process's surroundings leave any launch or resume to Python: a seat's,
// or surroundings that do.
func elsewhere() bool {
	return surroundings() || seated()
}

// surroundings is whether this process's surroundings leave a launch to Python: those unread, or a
// config Python refuses before its run.
func surroundings() bool {
	_, capped := config.MaxRuns()
	_, _, memory := config.RunMemoryMaxMB()
	return capped != nil || memory != nil || unread()
}

// unread is whether Go reads this process's surroundings otherwise than Python: a queued run's
// start, one a history.db that stands would record (no suite's sink marks it), one the
// gate does not admit outright, a home HOME does not name, or text Python would write with a lone
// surrogate.
func unread() bool {
	depth, known := runDepth()
	_, capped := config.MaxRuns()
	return os.Getenv("AGENTKIT_RUN_DIR") != "" || sink() == "" && !run.Historyless() ||
		os.Getenv("HOME") == "" || !known || capped == nil && os.Getenv("AK_MAX_RUNS") != "0" && depth == 0 ||
		!readable(run.Runs(), os.Getenv("AK_PARENT_RUN"), os.Getenv("AK_NOTIFY_SINK"))
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

// A place is what preflight settled of where a run it passes works: the repository, "" for a
// scratch task, its base, target, project (taskProject) and numbers, the checks a round runs, and
// the run under way it starts beside, told --anyway.
type place struct {
	repo, base, target, alongside string
	project                       string
	numbers                       config.Numbers
	every, once                   []string
}

// checkout is the checkout a launch of the task works in, "" for none, as Python's task_repo finds
// it; the refusal for a named one that is no git repository; ErrPython where it is Python's to find.
func checkout(meta map[string]string, path, copied string) (string, string, error) {
	switch named := meta["repo"]; {
	case strings.ToLower(named) == "none":
		return "", "", nil
	case named != "":
		if account, _, _ := strings.Cut(named, "/"); account != "~" && strings.HasPrefix(account, "~") {
			return "", "", ErrPython // a `~user`: that account's home is Python's to find
		}
		repo := config.Absolute(named)
		if !readable(repo) {
			return "", "", ErrPython
		}
		if found, err := exists(filepath.Join(repo, ".git")); err != nil || !found {
			return "", fmt.Sprintf("%s: repo %s is not a git repository", copied, repo), err
		}
		return repo, "", nil
	}
	top, err := taskProject("", path)
	if err != nil {
		return "", "", err
	}
	if top == "" {
		var found bool
		if top, _, found, err = git("", "rev-parse", "--show-toplevel"); err != nil || !found {
			return "", "", err
		}
	}
	if repo := config.Resolve(top); readable(repo) {
		return repo, "", nil
	}
	return "", "", ErrPython
}

// Budget is the rounds in force for a launch of the task at path, as Python's launch_policy reads
// them before anything else is judged: its checkout's, the host's where the task does not read or
// names a checkout that is none; ErrPython where the checkout is Python's to find, or the
// numbers Python's to carry (numbers).
func Budget(path string) (int, error) {
	repo := ""
	if meta, _, err := task.Read(path); err == nil {
		found, refused, err := checkout(meta, path, path)
		if err != nil {
			return 0, ErrPython
		}
		if refused == "" {
			repo = found
		}
	}
	numbers, err := numbers(repo, false)
	return numbers.Rounds, err
}

// preflight is why Python's preflight refuses the task, run from its copy, the warning its log says
// first, and where a run it passes works: a repository that is no git repository, a base git cannot
// read, more than 3 checks a round runs, or a `from:` the run cannot start from.  It leaves to
// Python a run whose suite is narrowed to its change, or whose landing checks run in pieces.
func preflight(meta map[string]string, cmds []string, path, copied, title string, values map[string]string, flags map[string]bool, bound config.Binding) (string, string, place, error) {
	var at place
	refuse := func(reason, warning string, err error) (string, string, place, error) {
		return reason, warning, at, err
	}
	repo, refused, err := checkout(meta, path, copied)
	if err != nil {
		return refuse("", "", err)
	}
	// a refused checkout is none (repo ""), so the host's numbers are in force, as in Budget
	if at.numbers, err = numbers(repo, false); errors.Is(err, ErrPython) {
		return refuse("", "", err)
	} else if err != nil {
		return refuse("", "", &refusedOutright{err.Error()})
	}
	// a change under way is refused next, as Python's already_under_way is
	found, err := rivals(repo, path, title, cmds)
	owner, _, _ := Seat()
	if err != nil {
		return refuse("", "", err)
	} else if len(found) > 0 && !flags["--anyway"] {
		return refuse("", "", &refusedOutright{underWayRefusal(found, owner != "")})
	} else if len(found) > 0 {
		at.alongside = found[0].id
	}
	// then the contract, which a task cannot supply, as Python's require_project_contract is
	if why := gitcall.ContractRefusal(repo); why != "" {
		return refuse("", "", &refusedOutright{why})
	}
	// a seat's launch is judged up to its queue, asked last before anything is created
	if owner != "" {
		if err := seatQueue(owner); err != nil {
			return refuse("", "", err)
		}
	}
	if refused != "" {
		return refuse(refused, "", nil)
	}
	at.repo = repo
	// a run belongs to the repository its task names, else to its task folder's checkout, never
	// to one it inherits from where it was launched
	worked := ""
	if meta["repo"] != "" {
		worked = repo
	}
	if at.project, err = taskProject(worked, path); err != nil {
		return refuse("", "", err)
	}
	landing := at.repo != "" && !flags["--no-merge"]
	at.target = cmp.Or(meta["target"], meta["base"])
	suite := ""
	if landing {
		spelled := at.target
		if spelled == "" {
			if head, _, ok, err := git(at.repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"); err != nil {
				return refuse("", "", err)
			} else if ok {
				spelled = head
			}
		}
		suite = run.DeclaredSuite(at.repo, spelled)
		if namesChanged.MatchString(suite) {
			return refuse("", "", ErrPython) // its suite runs every round, narrowed: Python's
		}
	}
	// what Python refuses after the base, settled first: finding the base may write origin/HEAD
	at.every, at.once = task.Group(task.RoundCommands(cmds, suite, landing))
	if slices.ContainsFunc(at.once, namesShard.MatchString) {
		return refuse("", "", ErrPython) // a landing check in pieces is Python's lander's
	}
	later := task.ChecksRefusal(at.every)
	switch from := meta["from"]; {
	case later != "" || from == "":
	case at.repo == "":
		later = copied + ": from: needs a repository; a scratch run has no branch to start from"
	case flags["--no-worktree"]:
		later = copied + ": from: needs a worktree; drop --no-worktree so the run gets its own checkout"
	default:
		branch, _, _, err := git(at.repo, "rev-parse", "--verify", "--quiet", "refs/heads/"+from)
		if err != nil {
			return refuse("", "", err)
		}
		if branch == "" {
			later = fmt.Sprintf("%s: from: %s is not a local branch", copied, commandhelp.Quote(from))
		}
	}
	if later == "" {
		// all that leaves a launch to Python is settled before anything is written
		if err := drivable(values, bound); err != nil {
			return refuse("", "", err)
		}
		// a repository run on a host with a helper is Python's: its rounds' checks and turns go there
		if at.repo != "" && helper.May() {
			return refuse("", "", ErrPython)
		}
	}
	if at.repo == "" {
		return refuse(later, "", nil)
	}
	warning := ""
	at.base = meta["base"]
	if at.base == "" {
		var err error
		if at.base, warning, err = gitcall.DefaultBase(at.repo); err != nil {
			return refuse(err.Error(), "", asPython(err))
		}
	}
	at.target = cmp.Or(meta["target"], at.base)
	if later != "" {
		return refuse(later, warning, nil)
	}
	return refuse("", warning, nil)
}

// A refusedOutright is a launch Python refuses before it makes a run directory.
type refusedOutright struct{ why string }

func (r *refusedOutright) Error() string { return r.why }

// asPython is ErrPython for a git that stopped, which Python says in its own words; a git that
// said no is the launch's refusal.
func asPython(err error) error {
	var stopped *gitcall.Stopped
	if errors.As(err, &stopped) {
		return ErrPython
	}
	return nil
}

// numbers is the numbers in force for a run in repo, the host's for none (run.LaunchPolicy), a
// task's refused where executors are off; ErrPython for those Go does not carry (run.Carried), read
// where Python's launch_policy is.
func numbers(repo string, review bool) (config.Numbers, error) {
	found, err := run.LaunchPolicy(repo)
	switch {
	case err != nil:
		return found, err
	case !review && found.ReviewLines == config.AtMost(0):
		return found, errors.New("executor_lines = 0: " + config.ExecutorsOff)
	case !run.Carried(found):
		return found, ErrPython
	}
	return found, nil
}

// git is git's stdout and stderr in repo ("" the current directory), stripped, and whether it
// exited 0; ErrPython where Python says what happened in its own words: a git that never answered
// or refused to prompt.
func git(repo string, args ...string) (string, string, bool, error) {
	code, stdout, stderr, err := gitcall.Git{Repo: repo}.Run(args...)
	if err != nil || gitcall.Halted(code, stderr) {
		return "", "", false, ErrPython
	}
	return gitcall.Strip(stdout), gitcall.Strip(stderr), code == 0, nil
}

// holdSlots waits for the lock every run's admission changes under.
func holdSlots() (*os.File, error) {
	return holdAdmission(context.Background())
}

func holdAdmission(ctx context.Context) (*os.File, error) {
	return lock.Wait(ctx, filepath.Join(run.Runs(), ".slots.lock"))
}

// receive writes the launch's receipt under the slots lock.
func receive(dir, path string, values map[string]string, flags map[string]bool, bound config.Binding, seat string) error {
	slots, err := holdSlots()
	if err != nil {
		return err
	}
	defer slots.Close()
	return receipt(dir, path, values, flags, bound, seat)
}

func receipt(dir, path string, values map[string]string, flags map[string]bool, bound config.Binding, seat string) error {
	return run.Create(dir, run.Capture(dir, path, values, flags, bound, seat))
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
