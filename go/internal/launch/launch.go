// Package launch starts a run from a task file as Python ak's `ak run <task.md>` does, up to
// its loop: the run's id and directory, the task's copy, the receipt, the gate's admission,
// preflight, and how a refused launch ends.  It hides which launches Go makes today: one on a
// path of Python's launch that Go has, which preflight refuses or whose run preflight passes, a
// scratch task's or a repository's with --no-merge or --no-worktree, a review of somebody else's
// pull request from no seat, or of a seat's own, and that run goes on in package loop.  A seat's launch it judges as
// Python's run.parse does, and one that passes is the seat's run: its receipt names the seat and
// binds the seat's lists and efforts, and the seat's bar and project follow it (seat.go).  Any
// other it leaves to Python (ErrPython), deciding so before it writes anything but the slots lock
// its admission is decided under (admit), so preflight is settled first.
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
	"regexp"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/handback"
	"agentkit/internal/history"
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
	l, text, err := typed(path)
	if err != nil {
		return 0, "", err
	}
	_, code, why, err := l.launch(path, text, values, flags, out, errOut)
	return code, why, err
}

// typed is the launcher of `ak run`'s launch of the task file at path, as it reads now, and what
// the file says; ErrPython for one Go does not read as Python does.
func typed(path string) (launcher, string, error) {
	data, err := os.ReadFile(path)
	bound, unbound := bind()
	if err != nil || !utf8.Valid(data) || unbound != nil {
		return launcher{}, "", ErrPython
	}
	seated, _, _ := Seat()
	return launcher{seat: seated, bound: bound}, task.Text(data), nil
}

// A launcher is who makes a launch and what its receipt binds: a seat's or the owner's `ak run`,
// or the tick's for no seat (Night), whose receipt says why the tick made it.  The tick's is
// Python's launch_for_seat: its run descends from nothing that made it, it asks no project
// contract, which only `ak run` asks (require_project_contract), it writes its task's files once
// the launch is known to be Go's, and it makes its pick first, refusing one no launch can make
// before a driver starts, since nobody follows its run to hear the driver say so.
type launcher struct {
	seat   string         // the seat whose launch it is, "" for none
	bound  config.Binding // the lists and efforts its receipt binds
	origin *run.Object    // why the tick made it, nil for `ak run`
	files  [][2]string    // the tick's task files, path and text; `ak run`'s task is written already
	job    *jobRun        // the job whose task it is, nil for none: it asks for a change under way itself
}

// launch is the launch of the task at path, text being what it says, as Task says, and the run's
// directory, "" where it made none.
func (l launcher) launch(path, text string, values map[string]string, flags map[string]bool, out, errOut io.Writer) (string, int, string, error) {
	at, code, why, err := l.judge(path, text, values, flags)
	if at == nil {
		return "", code, why, err
	}
	defer at.place.admitted.release()
	log, unstopped, err := at.make(out)
	if err != nil {
		return "", 0, "", err
	}
	reason := at.reason
	if reason == "" && l.origin != nil {
		reason = unstaffed(l.bound) // the tick's pick, made first
	}
	if reason == "" {
		code, err := drive(at.dir, at.meta, at.place, at.warning, flags, l.seat, unstopped, log, out, errOut)
		return at.dir, code, "", err
	}
	code, why, err = refuse(at.dir, reason, at.warning, log)
	return at.dir, code, why, err
}

// A launching is a launch as judge settled it, nothing written yet: the task file and what it
// says, its title and options, the run's directory, why preflight refuses it with the warning its
// log says first, and where a run it passes works.
type launching struct {
	launcher
	path, text, named, dir string
	meta                   map[string]string
	cmds                   []string
	values                 map[string]string
	flags                  map[string]bool
	reason, warning        string
	place                  place
	line                   any // the plan line its task serves (servedLine), which its receipt names
}

// judge is the launch of the task at path as preflight settles it; nil where it goes no further,
// with `ak run`'s exit status and why for one refused before any run directory, or ErrPython.
func (l launcher) judge(path, text string, values map[string]string, flags map[string]bool) (*launching, int, string, error) {
	meta, cmds, err := task.Parse(path, text)
	if err != nil || python(path, values, l.bound) {
		return nil, 0, "", ErrPython
	}
	// read before the receipt, as Python's capture_launch does: a refusal here leaves no run
	if _, err := config.MaxRuns(); err != nil {
		return nil, 2, err.Error(), nil
	}
	at := &launching{launcher: l, path: path, text: text, named: titleOf(path, text), meta: meta, cmds: cmds,
		values: values, flags: flags}
	if at.dir, err = freeDir(time.Now().Format("20060102-1504-") + task.Slug(at.named)); err != nil {
		return nil, 0, "", err
	}
	if at.line, err = servedLine(l.seat, cmds); err != nil {
		return nil, 0, "", err
	}
	at.reason, at.warning, at.place, err = l.preflight(meta, cmds, path, filepath.Join(at.dir, "task.md"), at.named, values, flags)
	var outright *refusedOutright
	if errors.As(err, &outright) {
		return nil, 2, outright.why, nil
	}
	if err != nil {
		at.place.admitted.release()
		return nil, 0, "", err
	}
	return at, 0, "", nil
}

// make writes the launch's run: the tick's task files, its directory, the task's copy, its log,
// its receipt and its title; with what says a line in its log and changes its record unless a stop
// landed.
func (at *launching) make(out io.Writer) (func(string) error, func(func(*run.Object)) error, error) {
	log, unstopped := logger(at.dir, out), guarded(at.dir, out)
	title := task.Title(at.text, "task")
	for _, step := range []func() error{
		config.EnsureDirs,
		at.write,
		func() error { return os.Mkdir(at.dir, 0o777) },
		func() error { return os.WriteFile(filepath.Join(at.dir, "task.md"), []byte(at.text), 0o666) },
		func() error { return os.WriteFile(filepath.Join(at.dir, "log.txt"), nil, 0o666) },
		func() error {
			return receive(at.dir, at.receipt(at.dir, at.path, at.values, at.flags, at.line), at.place.admitted)
		},
		func() error { recorded(at.dir); return nil },
		func() error { seat.Redress(at.seat); return nil }, // the seat's bar says it from the start
		func() error { return unstopped(func(record *run.Object) { record.Set("title", title) }) },
	} {
		if err := step(); err != nil {
			return nil, nil, err
		}
	}
	return log, unstopped, nil
}

// receipt is the launch's first record: what `ak run` records, the plan line it serves among it,
// with why the tick made it, and the job of a job's task, named in that first write as Python's
// capture_launch names it, so a stop knows it for one from the start.
func (l launcher) receipt(dir, path string, values map[string]string, flags map[string]bool, line any) *run.Object {
	record := run.SetAll(run.Capture(dir, path, values, flags, l.bound, l.seat), "plan_line", line)
	if l.job != nil {
		record.Set("job_id", l.job.id())
	}
	if l.origin != nil {
		for _, key := range l.origin.Keys() {
			record.Set(key, l.origin.Get(key))
		}
		run.SetAll(record, "run_depth", l.depth(), "parent_run", nil)
	}
	return record
}

// depth is the run depth of the launch's run: this process's for `ak run`, none for the tick's.
func (l launcher) depth() int {
	if l.origin != nil {
		return 0
	}
	depth, _ := runDepth()
	return depth
}

// titleOf is the title of the task at path holding text, as Python's parse_task gives it: its
// file's stem for none.
func titleOf(path, text string) string {
	stem := filepath.Base(path)
	if dot := strings.LastIndexByte(stem, '.'); 0 < dot && dot < len(stem)-1 {
		stem = stem[:dot]
	}
	return task.Title(text, stem)
}

// freeDir is the run's directory under that id, `-N` after it where the id is taken.
func freeDir(id string) (string, error) {
	return free(filepath.Join(run.Runs(), id))
}

// free is the path, `-N` after it where the path is taken.
func free(path string) (string, error) {
	named := path
	taken, err := exists(path)
	for n := 2; taken && err == nil; n++ {
		path = named + "-" + strconv.Itoa(n)
		taken, err = exists(path)
	}
	return path, err
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

// refuse ends a launch its receipt already records, as a run in error, Python's refused for the
// `ak run` typed: that command prints the refusal, so a seat's is handed back as printed there.
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
		func() error {
			// a stop that landed ends the row itself, as Python's stop does
			if ended.Str("state") != "stopped" {
				history.Finish(ended, func(line string) { log(line) })
				seat.Redress(run.Seat(ended)) // the ending lands on the bar too
			}
			return nil
		},
		func() error {
			// a result Python cannot write, or a stop's, goes untold
			if why := ended.Str("error"); run.Report(dir, ended) == nil && why != "" {
				return log("ERROR " + why)
			}
			return nil
		},
		func() error { return handback.PrintedAtLaunch(dir, func(line string) { log(line) }) },
	} {
		if err := step(); err != nil {
			return 0, "", err
		}
	}
	return 2, reason, nil
}

// python is whether Python ak makes this launch otherwise than Go would, or reads what Go
// cannot read as it does: any that leaves unread surroundings to Python, one naming no executor,
// a seat's whose runs Go cannot count its project from, or a string for the record Python would
// write with a lone surrogate.  A count that is none the gate never reads: Task refuses it.
func python(path string, values map[string]string, bound config.Binding) bool {
	name, _, unnamed := Seat()
	return unnamed != nil || unread("") || len(bound.Workers) == 0 || !readable(path) ||
		!readable(slices.Collect(maps.Values(values))...) || name != "" && !seat.Votes(name)
}

// elsewhere is whether this process's surroundings leave a launch, or the run id names going on,
// to Python: a seat's, or surroundings that do.
func elsewhere(id string) bool {
	return surroundings(id) || seated()
}

// surroundings is whether this process's surroundings leave a launch, or the run id names going
// on, to Python: one Python's gate decides, or surroundings that do whatever the gate decides.
func surroundings(id string) bool {
	depth, _ := runDepth()
	return gated(depth) || ungated(id)
}

// ungated is whether surroundings leave a launch, or the run id names going on, to Python
// whatever the gate decides: those unread, or a config Python refuses before its run.
func ungated(id string) bool {
	_, capped := config.MaxRuns()
	_, _, memory := config.RunMemoryMaxMB()
	return capped != nil || memory != nil || unread(id)
}

// unread is whether Go reads this process's surroundings otherwise than Python for a launch, or
// the run id names going on: a queued run's start; one a history Python kept would record (no
// suite's sink marks it) past the rows Go writes, any launch where it holds a run's step and a run
// Python carried, while one Go carried from its launch goes on as it began, a launch the gate
// decides left to its admission, which opens history.db only once Go goes on with the launch; a home
// HOME does not name, or text Python would write with a lone surrogate.
func unread(id string) bool {
	depth, known := runDepth()
	return os.Getenv("AGENTKIT_RUN_DIR") != "" || sink() == "" && !gated(depth) && history.Carried(id) ||
		os.Getenv("HOME") == "" || !known ||
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
// scratch task, its base, target, project (taskProject) and numbers, the checks a round runs, the
// run under way it starts beside, told --anyway, and the slot its gate let it into (admit).
type place struct {
	repo, base, target, alongside string
	project                       string
	numbers                       config.Numbers
	every, once                   []string
	admitted                      *admission
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
	if meta, _, err := task.Read(path); err == nil {
		return roundsFor(path, meta)
	}
	numbers, err := numbers("", false)
	return numbers.Rounds, err
}

// roundsFor is Budget of the task at path whose front matter is meta, written there or not yet.
func roundsFor(path string, meta map[string]string) (int, error) {
	repo, _, err := checkout(meta, path, path) // a refused checkout is none: repo ""
	if err != nil {
		return 0, ErrPython
	}
	numbers, err := numbers(repo, false)
	return numbers.Rounds, err
}

// preflight is why Python's preflight refuses the task, run from its copy, the warning its log says
// first, and where a run it passes works: a repository that is no git repository, a base git cannot
// read, more than 3 checks a round runs, or a `from:` the run cannot start from.  It leaves to
// Python a run whose suite is narrowed to its change, or whose landing checks run in pieces, and,
// where Python's gate decides the launch, a refusal it ends as a run in error, whose receipt Python
// writes queued for its slot.  A run it passes is admitted before it finds its base, which may
// write origin/HEAD.
func (l launcher) preflight(meta map[string]string, cmds []string, path, copied, title string, values map[string]string, flags map[string]bool) (string, string, place, error) {
	var at place
	refuse := func(reason, warning string, err error) (string, string, place, error) {
		if reason != "" && gated(l.depth()) {
			err = ErrPython
		}
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
	// a change under way is refused next, as Python's already_under_way is; only an owner's own
	// `ak run` may start a second run regardless.  A job's task is not asked: its job asked for
	// every task before its first, which no run of its own then rivals.
	if l.job == nil {
		found, err := rivals(repo, path, title, cmds)
		if err != nil {
			return refuse("", "", err)
		} else if len(found) > 0 && !flags["--anyway"] {
			return refuse("", "", &refusedOutright{underWayRefusal(found, l.seat != "" || l.origin != nil)})
		} else if len(found) > 0 {
			at.alongside = found[0].id
		}
	}
	// then the contract, which a task cannot supply, as Python's require_project_contract is
	if why := gitcall.ContractRefusal(repo); why != "" && l.origin == nil {
		return refuse("", "", &refusedOutright{why})
	}
	// a seat's launch is judged up to its queue, asked last before anything is created; a job's
	// task is not asked, its job's launch having asked for every task (check_seat_queue)
	if l.seat != "" && l.job == nil {
		if err := seatQueue(l.seat); err != nil {
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
	}
	// what Python refuses after the base, settled first: finding the base may write origin/HEAD
	at.every, at.once = task.Group(task.RoundCommands(cmds, suite, landing))
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
		if err := drivable(values, l.bound); err != nil {
			return refuse("", "", err)
		}
		if at.repo != "" && machined() {
			return refuse("", "", ErrPython)
		}
	}
	if later != "" && (at.repo == "" || gated(l.depth())) {
		return refuse(later, "", nil)
	}
	// copied is the run's own task.md: its folder names the run; told --bg, nothing here follows it
	if at.admitted, err = admit(filepath.Base(filepath.Dir(copied)), flags["--first"], l.seat, l.depth(), !flags["--bg"]); err != nil || at.repo == "" {
		return refuse("", "", err)
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
// task's refused where executors are off (run.TaskPolicy); ErrPython for those Go does not carry
// (run.Carried), read where Python's launch_policy is.
func numbers(repo string, review bool) (config.Numbers, error) {
	read := run.TaskPolicy
	if review {
		read = run.LaunchPolicy
	}
	found, err := read(repo)
	switch {
	case err != nil:
		return found, err
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

// plainDecimal is a poll both Python's float() and Go read alike.
var plainDecimal = regexp.MustCompile(`^[0-9]+(\.[0-9]+)?$`)

// slotPoll is the seconds between a waiting run's polls, AK_SLOT_POLL as Python's gate reads it,
// 30 where unset; false where it holds what Python's float() might read otherwise than Go.
func slotPoll() (float64, bool) {
	text, set := os.LookupEnv("AK_SLOT_POLL")
	if !set {
		return 30, true
	}
	poll, err := strconv.ParseFloat(text, 64)
	return poll, err == nil && plainDecimal.MatchString(text)
}

// receive writes the launch's receipt under the slots lock: in the hold its admission took, claiming
// the slot it was let into, else in one of its own.
func receive(dir string, record *run.Object, admitted *admission) error {
	if admitted != nil {
		return admitted.claim(dir, record)
	}
	slots, err := holdSlots()
	if err != nil {
		return err
	}
	defer slots.Close()
	return run.Create(dir, record)
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
