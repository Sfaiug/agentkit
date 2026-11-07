package tick

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// stallCleanup is the seconds past a run's silence limit the loop's own watchdog gets to end a
// silent turn and record it first: its kill grace and two of its polls (watch.stall_allowance).
const stallCleanup = 7

// stallRecovery is watch.recover_runs: a hung model or test would otherwise hold a slot and its
// seat for ever, so every running run silent past the limit it launched with, measured from
// outside by its newest write, climbs one rung a tick (`rung`), and a parked run whose notice did
// not go out is told again.  A slot waiter whose process died, a loop the host froze and a rung Go
// does not carry are Python's, handed over before anything of that run is written.
func (t *ticking) stallRecovery() error {
	if !run.Every(func(dir string, record *run.Object) bool {
		err := t.climb(dir, record)
		if err != nil && !errors.Is(err, errLeft) {
			t.log.line(fmt.Sprintf("WARN cannot check run %s: %s", filepath.Base(dir), config.PyError(err)))
		}
		return !errors.Is(err, errLeft)
	}) {
		return errLeft
	}
	return nil
}

// climb is the stall row's work on one run.
func (t *ticking) climb(dir string, record *run.Object) error {
	now, id := epoch(t.clock()), filepath.Base(dir)
	switch state := record.Str("state"); {
	case state == "queued" && record.Truthy("slot_waiting"):
		if run.ProcessActive(record) || run.ResumeOrdered(record, now) {
			return nil
		}
		return errLeft
	case state == "stalled" && !record.Truthy("stalled_notified"):
		if t.dry {
			t.log.line("would notify the parking of " + id + " again")
			return nil
		}
		return t.tellParked(dir)
	case state != "running", run.ResumeOrdered(record, now) && !run.ProcessActive(record):
		// a resume already ordered adopts the dead loop: measuring it would launch a second one
		return nil
	}
	pid, _ := record.Int("pid")
	if _, read := silenceLimit(record); !read || record.Truthy("frozen_since") || run.ProcessActive(record) && host.Frozen(pid) {
		return errLeft // a freeze pauses the stall clock, which Python keeps, as it reads a limit Go does not
	}
	r, due := rungOf(dir, record, now)
	switch {
	case !due:
		return nil
	case t.dry:
		t.log.line(fmt.Sprintf("would %s %s, silent for %s: %s", r.name(), id, run.Span(r.silent), r.line))
		return nil
	}
	release, err := run.Hold(dir)
	if err != nil {
		return err
	}
	climbed, err := t.climbUnder(dir, &r, now)
	if climbed != nil {
		switch r.name() {
		case "park":
			loop.WriteResult(dir, climbed)
			run.Note(dir, r.line+"; parked as stalled", t.clock())
			err = t.tellParked(dir)
			t.log.line(fmt.Sprintf("%s: %s; parked as stalled", id, r.line))
		case "resume":
			run.Note(dir, r.line+"; resumed", t.clock())
			t.log.line(fmt.Sprintf("%s: %s; resumed", id, r.line))
		default:
			run.Note(dir, r.line, t.clock())
			t.log.line(fmt.Sprintf("%s: %s", id, r.line))
		}
	}
	release()
	if climbed == nil || r.name() != "resume" {
		return err
	}
	code, why, err := launch.ResumeExpected(id, climbed, nil, nil)
	switch {
	case errors.Is(err, launch.ErrPython):
		return errLeft
	case err != nil || code != 0:
		t.log.line(fmt.Sprintf("WARN could not resume %s: %s", id, cmp.Or(why, fmt.Sprint(err))))
	}
	return nil
}

// climbUnder takes the run one rung down under its lock, read again there into r: the record as it
// was written, nil where the run moved on or the rung is Python's.  Each rung ends only what the
// record names, matched by identity: the loop's child as it was read, the loop itself as recorded.
func (t *ticking) climbUnder(dir string, r *rung, now float64) (*run.Object, error) {
	id := filepath.Base(dir)
	var climbed *run.Object
	err := run.Change(dir, func(current *run.Object) error {
		due := false
		if *r, due = rungOf(dir, current, now); current.Str("state") != "running" || !due {
			return nil
		}
		stalls := slices.Clone(r.stalls)
		entry := func(action string) *run.Object {
			return run.Fields("time", epoch(t.clock()), "round", r.round, "step", r.step, "action", action)
		}
		switch r.name() {
		case "park":
			if r.alive && scoped(current) || !typable(run.Seat(current), parkedLine(id, r.step)) {
				return errLeft // Python stops a unit by its name, and cards or pages a seat it cannot type into
			}
			r.endLoop(current)
			run.SetAll(current, "state", "stalled", "stalls", append(stalls, entry("parked")), "finished_at", nil,
				"stalled_notified", false, "error", fmt.Sprintf("stalled three times at %s; parked: ak run resume %s", r.step, id))
		case "resume":
			// reap leaves the ended loop alone, and the resume adopts it
			order := func(record *run.Object) { record.Set("stall_resume_at", now) }
			if r.kind == "worker" || !launch.Takes(id, current, order) {
				return errLeft // a stalled worker turn goes to another executor, which Python picks
			}
			r.endLoop(current)
			order(current)
			current.Set("stalls", append(stalls, entry("resumed")))
		default:
			action := "step already gone"
			for _, child := range host.Children(r.pid) {
				if child.Pid == r.child.Pid && child.Start == r.child.Start && slices.Equal(child.Args, r.child.Args) && child.Pid != os.Getpid() {
					host.EndTree(child.Pid)
					action = "killed step"
				}
			}
			current.Set("stalls", append(stalls, entry(action)))
		}
		climbed = current
		return nil
	})
	if err != nil {
		return nil, err
	}
	return climbed, nil
}

// A rung is where a silent run stands on the ladder, read off its record and its loop's children.
type rung struct {
	alive      bool
	pid        int
	kind, step string // the loop's child: a `worker` or `reviewer` turn, the `done-when` gate, or `none`
	child      host.Child
	round      int
	stalls     []any
	silent     float64 // seconds
	line       string
}

// rungOf is where that run stands, and whether it is due: silent past its limit and the cleanup.
func rungOf(dir string, record *run.Object, now float64) (rung, bool) {
	minutes, _ := silenceLimit(record)
	r := rung{alive: run.ProcessActive(record), kind: "none", step: "loop gone", stalls: record.List("stalls"),
		silent: now - stallClock(dir, record, now), round: len(record.List("round_summaries")) + 1}
	r.pid, _ = record.Int("pid")
	if r.alive {
		r.kind, r.step, r.child = stepOf(record, r.pid)
	}
	r.line = fmt.Sprintf("stall: no output for %s min in round %d (%s)",
		run.Field(record, "silence_minutes", strconv.Itoa(run.SilenceMinutes)), r.round, r.step)
	return r, r.silent >= minutes*60+stallCleanup
}

// name is the rung: the step's tree first, then the loop with a resume, then parking; a loop with
// no child has no step to end.
func (r rung) name() string {
	switch {
	case len(r.stalls) >= 2:
		return "park"
	case len(r.stalls) >= 1 || r.kind == "none":
		return "resume"
	}
	return "kill the step"
}

// endLoop ends what the record names of a live loop, where no unit holds it: every process
// carrying its run's marker, then the loop's own tree (watch.stop_run_scope, kill_tree).
func (r rung) endLoop(record *run.Object) {
	if !r.alive {
		return
	}
	if record.Truthy("run_id") {
		host.EndMarked(filepath.Join(run.Runs(), record.Str("run_id")), io.Discard)
	}
	host.EndTree(r.pid)
}

// stepOf is what the loop is doing, off its lowest child (watch.step_for_run): a reviewer turn's
// out-dir carries `/reviewer`.
func stepOf(record *run.Object, pid int) (string, string, host.Child) {
	children := host.Children(pid)
	if len(children) == 0 {
		return "none", "no child", host.Child{}
	}
	child := children[0]
	args := child.Args
	if workerTurn(args) {
		if slices.ContainsFunc(args, func(arg string) bool { return strings.Contains(arg, "/reviewer") }) {
			return "reviewer", "reviewer: " + named(record, "reviewer", "reviewer"), child
		}
		return "worker", "worker: " + named(record, "executor", "worker"), child
	}
	command := strings.TrimFunc(strings.Join(args, " "), config.Space)
	if len(args) >= 3 && filepath.Base(args[0]) == "bash" && args[1] == "-c" {
		command = strings.TrimFunc(args[2], config.Space)
	}
	if command == "" {
		command = "(unknown command)"
	}
	if runes := []rune(command); len(runes) > 200 {
		command = string(runes[:200])
	}
	return "done-when", "done-when: " + command, child
}

// named is the model the record names in that role, else the word for it.
func named(record *run.Object, role, word string) string {
	if record.Truthy(role) {
		return run.Text(record.Get(role))
	}
	return word
}

// workerTurn is whether the loop's child is a worker turn, its harness's adapter, rather than the
// done-when gate, by its program alone (watch.is_worker_cmd): a gate grepping its own logs, or a
// test file named after a role, must not read as one.
func workerTurn(args []string) bool {
	if len(args) == 0 {
		return false
	}
	if strings.ToLower(filepath.Base(filepath.Dir(args[0]))) == "adapters" {
		return true
	}
	name := strings.ToLower(filepath.Base(args[0]))
	if slices.Contains([]string{"", ".", "/", "bash", "sh", "sleep", "flock", "env", "python3", "python"}, name) {
		return false
	}
	for _, model := range run.Models() {
		if model.Harness != "" && strings.Contains(name, strings.ToLower(model.Harness)) {
			return true
		}
	}
	return false
}

// silenceLimit is the minutes of silence the run launched with; false for one Go does not read.
func silenceLimit(record *run.Object) (float64, bool) {
	if !record.Has("silence_minutes") {
		return run.SilenceMinutes, true
	}
	minutes, known := dated(record, "silence_minutes")
	return minutes, known && minutes > 0
}

// stallClock is when the run's silence began (watch.stall_clock): its newest write, the thaw that
// restarted the clock, or the end of the transient wait its own loop sleeps out, and now while its
// live loop waits on another delivery's repository lock.  A resume after a death is a new loop,
// whose silence is its own.
func stallClock(dir string, record *run.Object, now float64) float64 {
	pid := record.Get("pid")
	if record.Truthy("delivery_wait") && run.Equal(record.Get("delivery_wait"), pid) && record.Str("state") == "running" &&
		run.ProcessActive(record) {
		return now
	}
	latest := max(run.LastWrite(dir), run.FirstNumber(record, "thawed_at"))
	if wait := record.Dict("transient_wait"); wait != nil && run.Equal(wait.Get("pid"), pid) {
		latest = max(latest, run.FirstNumber(wait, "until"))
	}
	return latest
}
