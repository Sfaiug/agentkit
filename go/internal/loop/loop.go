// Package loop drives one run of a task from its slot to its result, as Python's drive, loop,
// rounds, execute, verify_work, review, write_result and finish do on the road a passing run takes.
// Its interface is small: Start gives a launched run a driver process of its own, Follow shows a
// terminal what that driver does until it is gone, Drive is that driver, End is its ending in
// error, and Clean takes a run's checkout.
//
// It hides the stages (the workplace, the models, the executor's turn, the checks, the reviewer's
// verdict, the delivery), the round files under <run>/round-N, and the locks: every record is
// written through run.Change, under the run's own locks, by rename.
//
// The driver is a process of each run's own, which a foreground `ak run` follows, rather than one
// process from launch to result: Go cannot fork, so `--bg` needs a process started anew anyway, and
// with one the two launches are the same road, and a terminal closing leaves the run going.
//
// A run's record is Python's, so what Go does not carry out of it is Python's too: a stop, a resume
// and a driver that died are a run like its own to Python.  Any other road Go does not carry out
// ends the run in error, with a reason naming that road (notYet).
package loop

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
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/task"
	"agentkit/internal/usage"
)

// DriveFlag is the `ak run` word a driver process is started with: its cmdline still names
// `ak run`, which is how Python's process_active knows one with no identity on the record.
const DriveFlag = "--drive"

// ErrStopped is a run a stop ended before its driver started.
var ErrStopped = errors.New("a run a stop ended")

// followEvery is how often a terminal following a run looks for more: reading a file is cheap,
// and a run that just ended should not hold the terminal.
const followEvery = 200 * time.Millisecond

// errStop is a run a stop landed on: the record says so, and nothing is written over it.
var errStop = errors.New("the run was stopped")

// signalNames are the signals that end a driver's turn; the context ends with the one that came.
var signalNames = map[os.Signal]string{syscall.SIGTERM: "SIGTERM", syscall.SIGINT: "SIGINT", syscall.SIGHUP: "SIGHUP"}

// A blocked is a task that cannot be done as written, as an executor handed it in.
type blocked struct{ why, section string }

func (b *blocked) Error() string { return b.why }

// notYet is the reason a run ends in error on a road Go does not carry out.
func notYet(what, road string) error {
	return fmt.Errorf("%s: %s is not Go's yet", what, road)
}

// Start gives the launched run at dir a driver process of its own, under the locks the driver
// waits on, so a record that names it is written before it reads one, as Python's spawn_bg, and
// says on out where to look.  That transfers the slot the launch's receipt claimed, so the launch
// calls it under the slots lock.
func Start(dir string, out io.Writer) error {
	started := run.Change(dir, func(record *run.Object) error {
		if record.Str("state") == "stopped" {
			return ErrStopped
		}
		pid, err := spawn(dir)
		if err != nil {
			return err
		}
		var identity any
		if born, ok := host.ReadIdentity(pid); ok {
			identity = run.Fields("boot", born.Boot, "ticks", int(born.Ticks), "started_at", born.StartedAt)
		}
		run.SetAll(record, "state", "running", "slot_waiting", false, "launch_pending", false, "pid", pid,
			"process_identity", identity, "scope", "none", "scope_reason", "no user systemd manager")
		record.Delete("reservation_pending")
		return nil
	})
	if errors.Is(started, ErrStopped) {
		return started
	}
	if started != nil {
		reason := "Could not launch the run: " + started.Error()
		End(dir, reason)
		return errors.New(reason)
	}
	appendLog(dir, stamped("scope: none (no user systemd manager)"))
	fmt.Fprintf(out, "%s\n%s\n", filepath.Base(dir), filepath.Join(dir, "result.md"))
	return nil
}

// spawn starts the run's driver in a session of its own, writing to the run's log, and reaps it
// when it ends: a zombie still answers as alive.
func spawn(dir string) (int, error) {
	self, err := os.Executable()
	if err != nil {
		return 0, err
	}
	log, err := os.OpenFile(filepath.Join(dir, "log.txt"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
	if err != nil {
		return 0, err
	}
	defer log.Close()
	cmd := exec.Command(self, "run", DriveFlag, dir)
	cmd.Stdout, cmd.Stderr, cmd.SysProcAttr = log, log, host.Detached()
	if err := cmd.Start(); err != nil {
		return 0, err
	}
	go cmd.Wait()
	return cmd.Process.Pid, nil
}

// Follow shows out what the run's log holds past offset until its driver is gone, then answers
// from the record, `ak run`'s exit status as Python's follow_run says it.  A run still going with
// its driver gone is left as it is for Python's tick, which Python's follow waits on.
func Follow(dir string, offset int64, out, errOut io.Writer) int {
	log, err := os.Open(filepath.Join(dir, "log.txt"))
	if err != nil {
		return 2
	}
	defer log.Close()
	log.Seek(offset, io.SeekStart)
	for {
		io.Copy(out, log)
		record, _ := run.Read(dir)
		if record == nil || !run.ProcessActive(record) {
			break
		}
		time.Sleep(followEvery)
	}
	io.Copy(out, log)
	record, _ := run.Read(dir)
	if record != nil && run.Active(record) {
		fmt.Fprintln(errOut, "the run's driver died; ak's tick carries it on")
		return 1
	}
	// a --no-merge launch runs in Python's own foreground, where bin/ak says why it ended in error
	if opts := launchOpts(record); record != nil && record.Str("state") == "error" && record.Truthy("error") && opts != nil && opts.Truthy("--no-merge") {
		fmt.Fprintln(errOut, "ak run: "+record.Str("error"))
	}
	return exitStatus(record)
}

func launchOpts(record *run.Object) *run.Object {
	if record == nil {
		return nil
	}
	return record.Dict("launch_opts")
}

// exitStatus is `ak run`'s exit status for a run's ending, as Python's follow_run says it.
func exitStatus(record *run.Object) int {
	switch {
	case record == nil:
		return 1
	case record.Str("state") == "error":
		return 2
	case record.Str("state") == "not_needed":
		return 0
	case record.Str("state") == "pass" && run.ReviewPass(record, run.Models()) && !record.Truthy("merge_failed"):
		return 0
	}
	return 1
}

// A loop is one driver's run.
type loop struct {
	ctx         context.Context
	dir         string
	id          string
	body        string
	every       []string // the done-when lines as a round runs them
	prompt      string
	workspace   string
	place       workplace
	title       string
	cmds        []string // the done-when lines a round reads
	usersAt     string   // the ref a review's `users:` is read at
	reviewLines int      // the first review's ceiling
	once        []string // those deferred to landing
	executor    string
	reviewer    string
	workers     []string // the lists the run was launched with, nil where none was bound
	reviewers   []string
	efforts     *run.Object
	silence     time.Duration
	ceiling     time.Duration
}

// Drive is the driver process of the run at dir, its exit status the ending's.  It is no turn, so
// nothing it runs hands in to one above it.
func Drive(dir string) (code int) {
	defer func() {
		if failure := recover(); failure != nil {
			code = End(dir, fmt.Sprintf("the driver failed: %v", failure))
		}
	}()
	host.Lower()
	for _, name := range []string{"AK_HAND_IN", "AK_HAND_IN_CONTINUE", "AK_HAND_IN_FINDINGS"} {
		os.Unsetenv(name)
	}
	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)
	told := make(chan os.Signal, 1)
	signal.Notify(told, slices.Collect(maps.Keys(signalNames))...)
	go func() { cancel(fmt.Errorf("the driver got %s", signalNames[<-told])) }()
	l := &loop{ctx: ctx, dir: dir, id: filepath.Base(dir)}
	err := l.adopt()
	if err == nil {
		l.say(fmt.Sprintf("run %s: %s", l.id, filepath.Join(dir, "task.md")))
		err = l.work()
	}
	return l.finish(err)
}

// adopt takes the run over from its launch, as Python's wait_for_slot finds a slot already
// claimed: Start spawned this process inside its own change, so this one reads the record naming it.
func (l *loop) adopt() error {
	return run.Change(l.dir, func(record *run.Object) error {
		pid, _ := record.Int("pid")
		switch {
		case record.Str("state") == "stopped":
			return errStop
		case pid != os.Getpid() && run.ProcessActive(record):
			return errStop // it is that process's to end
		case record.Str("state") != "running" || pid != os.Getpid():
			return errors.New(l.id + ": another process owns this launch")
		}
		depth, _ := record.Int("run_depth")
		parent := record.Str("parent_run")
		if parent == "" {
			parent = l.id
		}
		os.Setenv("AK_RUN_DEPTH", strconv.Itoa(depth+1))
		os.Setenv("AK_PARENT_RUN", parent)
		os.Setenv(host.Marker, l.dir)
		l.workers, l.reviewers = names(record.List("workers")), names(record.List("reviewers"))
		l.efforts = record.Dict("efforts")
		minutes, _ := record.Num("silence_minutes")
		hours, _ := record.Num("ceiling_hours")
		l.silence = time.Duration(minutes * float64(time.Minute))
		l.ceiling = time.Duration(hours * float64(time.Hour))
		return nil
	})
}

// save changes the record as it stands, unless a stop landed or a signal came.
func (l *loop) save(change func(*run.Object)) error {
	if l.ctx.Err() != nil {
		return context.Cause(l.ctx)
	}
	return write(l.dir, change)
}

// write is save for an ending, which no signal holds back: a stop that landed stands.
func write(dir string, change func(*run.Object)) error {
	return run.Change(dir, func(record *run.Object) error {
		if record.Str("state") == "stopped" {
			return errStop
		}
		change(record)
		return nil
	})
}

// stopCheck is nil where work may go on, as Python's stop_check, read under the lock a stop marks
// under, so a checker queued behind the stop never starts what the sweep already passed.
func (l *loop) stopCheck() error {
	return l.save(func(*run.Object) {})
}

// say is one line of the run's log, with its time.
func (l *loop) say(message string) {
	appendLog(l.dir, stamped(message))
}

func stamped(message string) string {
	return time.Now().Format("[15:04:05] ") + message + "\n"
}

func appendLog(dir, text string) {
	log, err := os.OpenFile(filepath.Join(dir, "log.txt"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
	if err != nil {
		return
	}
	defer log.Close()
	log.WriteString(text)
}

// A stampedLog writes each line given it as a line of the run's log with its time.
type stampedLog struct{ dir string }

func (w stampedLog) Write(data []byte) (int, error) {
	for _, line := range config.SplitLines(string(data)) {
		appendLog(w.dir, stamped(line))
	}
	return len(data), nil
}

// A rawLog writes what it is given into the run's log as it is.
type rawLog struct{ dir string }

func (w rawLog) Write(data []byte) (int, error) {
	appendLog(w.dir, string(data))
	return len(data), nil
}

// work is the run's stages, and whatever ends them early.
func (l *loop) work() error {
	if err := l.open(); err != nil {
		return err
	}
	if err := l.pick(); err != nil {
		return err
	}
	if err := l.round(); err != nil {
		return err
	}
	return l.place.finished(l)
}

// open writes down what the run is and makes its workplace, Python's loop up to its first pick.
func (l *loop) open() error {
	path := filepath.Join(l.dir, "task.md")
	meta, cmds, err := task.Read(path)
	if err != nil {
		return err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	text := task.Text(data)
	l.body = task.Body(text)
	l.title = task.Title(text, "task")
	words, points := task.Size(l.body)
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "run_id", l.id, "title", l.title, "task", path, "state", "running", "verdict", nil,
			"started_at", clock(), "reported", false, "task_words", words, "task_points", points, "task_checks", len(cmds))
	}); err != nil {
		return err
	}
	rounds, method, err := budget(meta, path, l.dir)
	if err != nil {
		return err
	}
	record, err := run.Read(l.dir)
	if record == nil {
		return cmp.Or(err, errors.New("run.json cannot be read"))
	}
	files := task.Files(text)
	l.place = placeOf(record)
	l.reviewLines = numbersOf(record)
	if repo, isRepo := l.place.(*repoPlace); isRepo {
		repo.title, repo.files = l.title, files
	}
	if err := l.place.open(l, meta, path, []any{"stalls", []any{}, "executor", nil, "reviewer", nil, "rounds", rounds,
		"finished_at", nil, "round_summaries", []any{}, "findings", "", "merge_method", method,
		"pr", nil, "merged", false, "merge_note", nil}); err != nil {
		return err
	}
	landing, suite := l.place.landing()
	l.cmds = task.RoundCommands(cmds, suite, landing)
	l.every, l.once = task.Group(l.cmds)
	l.body += l.place.rules()
	scope := ""
	if len(files) > 0 {
		scope = "\n\nfiles: " + strings.Join(files, ", ")
	}
	checks := make([]string, len(l.every))
	for i, cmd := range l.every {
		checks[i] = "  $ " + cmd
	}
	l.prompt = fmt.Sprintf("%s\n\n%s\n\n%s\n\nDone-when commands, all must exit 0 (run them in %s):\n%s",
		l.place.where(l), l.body, foreground, l.workspace, strings.Join(checks, "\n"))
	if len(l.once) > 0 {
		l.prompt += "\nThe loop runs these once at landing on the commit to be merged; do not run them yourself:"
		for _, cmd := range l.once {
			l.prompt += "\n  $ " + cmd
		}
	}
	l.prompt += scope
	l.body += scope
	return nil
}

// budget is the task's round budget and merge method, as Python's loop refuses them: the launch's
// `--rounds`, else the task's own line, else the host's policy.
func budget(meta map[string]string, path, dir string) (rounds int, method string, err error) {
	record, err := run.Read(dir)
	if record == nil {
		return 0, "", cmp.Or(err, errors.New("run.json cannot be read"))
	}
	raw := ""
	if opts := record.Dict("launch_opts"); opts != nil {
		raw = opts.Str("--rounds")
	}
	if raw == "" {
		raw = meta["rounds"]
	}
	number, err := config.Rounds()
	if err != nil {
		return 0, "", err
	}
	if policy := record.Dict("policy"); policy != nil {
		if held, ok := policy.Int("rounds"); ok {
			number = held
		}
	}
	if raw != "" {
		parsed := config.Int(raw)
		if parsed == nil || parsed.Sign() < 1 || !parsed.IsInt64() {
			return 0, "", fmt.Errorf("%s: rounds must be a positive integer (got %s)", path, quoted(raw))
		}
		number = int(parsed.Int64())
	}
	method = strings.ToLower(meta["merge"])
	if method == "" {
		method = "squash"
	}
	if method != "squash" && method != "merge" && method != "rebase" {
		return 0, "", fmt.Errorf("%s: merge must be one of squash, merge, rebase (got %s)", path, quoted(meta["merge"]))
	}
	return number, method, nil
}

// names is the record's list as names.
func names(list []any) (found []string) {
	for _, name := range list {
		found = append(found, run.Text(name))
	}
	return found
}

// rules is what every pick of this run reads: the lists it was launched with, Python's run_workers
// and run_reviewers, as the config can change while it lives; the config's own where none was bound.
func (l *loop) rules() (*pick.Rules, bool) {
	if l.workers == nil {
		return pick.Load()
	}
	return pick.Within(l.workers, l.reviewers)
}

// pick chooses who executes and who reviews, as Python's pick_models and best_pair: a harness that
// cannot run a turn here is left out before any budget rule reads the list.
func (l *loop) pick() error {
	rules, ok := l.rules()
	if !ok {
		return notYet("the models cannot be picked here", "a pick Python makes")
	}
	readings, err := usage.Read()
	if err != nil {
		return notYet("the meters cannot be read: "+err.Error(), "a pick without them")
	}
	room := withRoom(readings)
	logged := rawLog{l.dir}
	rules.Order(room, false, logged)
	rules.Order(room, true, logged)
	executor, reviewer, found := rules.Pair(room)
	if !found {
		return notYet("no executor and reviewer can run now", "an exhausted run")
	}
	l.executor, l.reviewer = executor, reviewer
	var rounds int
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "executor", executor, "reviewer", reviewer)
		rounds, _ = record.Int("rounds")
	}); err != nil {
		return err
	}
	l.say(fmt.Sprintf("executor=%s reviewer=%s rounds=%d", executor, reviewer, rounds))
	return nil
}

// finish is how a run ends once its work stopped, as Python's loop and finish say it.
func (l *loop) finish(err error) int {
	var cannot *blocked
	switch {
	case errors.Is(err, errStop):
		return 1
	case errors.As(err, &cannot):
		l.say("BLOCKED " + cannot.why)
		err = write(l.dir, func(record *run.Object) {
			run.SetAll(record, "state", "blocked", "verdict", "BLOCKED", "error", cannot.why,
				"blocked", cannot.section, "finished_at", clock())
		})
	case err != nil:
		var stopped *gitcall.Stopped
		if errors.As(err, &stopped) {
			err = notYet(stopped.Why, "a git that stopped")
		}
		return End(l.dir, err.Error())
	default:
		err = write(l.dir, func(record *run.Object) {
			state := "fail"
			if run.ReviewPass(record, run.Models()) {
				state = "pass"
			}
			run.SetAll(record, "state", state, "finished_at", clock())
		})
	}
	if errors.Is(err, errStop) {
		return 1
	}
	return conclude(l.dir)
}

// End is the driver's own ending in error, why its reason, as Python's mark_state: the verdict it
// reached stands, as does a stop that landed or an ending already written.  A driver that could not
// start ends its run here too.  It is the exit status of the ending.
func End(dir, why string) int {
	err := run.Change(dir, func(record *run.Object) error {
		if !run.Active(record) {
			return errStop
		}
		run.SetAll(record, "state", "error", "error", why, "finished_at", clock())
		return nil
	})
	if err != nil {
		record, _ := run.Read(dir)
		return exitStatus(record)
	}
	return conclude(dir)
}

// conclude is what follows an ending on the record: its result, what it left running, ended once,
// and the log's last word.
func conclude(dir string) int {
	record, _ := run.Read(dir)
	if record == nil {
		return 2
	}
	said := stampedLog{dir}
	if record.Truthy("error") && !(record.Truthy("worktree") && record.Has("round_summaries")) {
		// nothing to report on but why: its reason is said here, as Python's record_result does
		fmt.Fprintln(said, "ERROR "+record.Str("error"))
	}
	WriteResult(dir, record)
	host.EndMarked(dir, said)
	// said on the record, so nothing reaps it again
	write(dir, func(record *run.Object) {
		record.Set("tree_stopped", []any{record.Get("pid"), record.Get("process_identity")})
	})
	if record.Str("state") == "error" {
		fmt.Fprintln(said, "FAIL -> "+filepath.Join(dir, "result.md")+" (error)")
		return 2
	}
	fmt.Fprintln(said, run.Delivery(record, run.Models())+" -> "+filepath.Join(dir, "result.md"))
	return exitStatus(record)
}

func clock() float64 { return float64(time.Now().UnixNano()) / 1e9 }

// quoted is text as Python's repr shows it.
func quoted(text string) string {
	return "'" + strings.ReplaceAll(text, "'", `\'`) + "'"
}
