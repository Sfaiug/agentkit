package loop

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/usage"
	"agentkit/internal/worker"
)

const (
	killWindow = time.Minute // a second signal inside this parks the run for a person

	noVerdictAsk = "Your previous turn ended without ak hand-in done. Review the diff now, hand in any remaining findings or follow-ups with ak hand-in, then run ak hand-in done. Earlier records have been carried into this turn. Do not start commands you will not wait for in this turn."
)

// A transient answer is what a person answers by typing `continue`: the same session again, after
// these waits, then hourly, indefinitely.  The run stays `running` throughout.
var transientBackoff = []time.Duration{time.Minute, 5 * time.Minute, 15 * time.Minute, 30 * time.Minute, time.Hour}

// transientDelay is how long the attempt-th transient retry waits: the backoff's steps, then hourly.
func transientDelay(attempt int) time.Duration {
	if attempt <= len(transientBackoff) {
		return transientBackoff[attempt-1]
	}
	return time.Hour
}

// A cannotRun is a harness that never ran the turn: another provider takes it, or the run is
// blocked on this line, which is what it is wherever nobody catches it.
type cannotRun struct{ name, line string }

func (c *cannotRun) detail() string { return "cannot run: " + c.line }
func (c *cannotRun) Error() string  { return c.name + " " + c.detail() }
func (c *cannotRun) Unwrap() error {
	return &blocked{c.Error(), "## Blocked\n\n" + c.Error()}
}

// A ranDry is a provider's refusal for a spent window: the work goes to another, not another try.
type ranDry struct {
	mark, out, message string // out: the attempt refused, which holds what the turn handed in
	code               int
}

func (r *ranDry) Error() string { return "refused: " + r.message }

// A handedOver is a worker that failed on its provider twice in a row, its role moved to next.
type handedOver struct{ before, next string }

func (h *handedOver) Error() string {
	return h.before + " failed on the provider twice; handed to " + h.next
}

// A try is one attempt of a call, what the faults read.
type try struct {
	out, text, session, resumed string // resumed: the conversation it went on, "" for a new one
	code                        int
	asked                       bool // the call's first: resumed is the conversation it was told to go on
	silent                      bool // stopped for streaming nothing
}

// A call is one turn of a model on the road Python's call_retrying takes: it goes again while the
// harness keeps dying on the provider instead of the task, each attempt in a directory of its own,
// so a failed one's stderr.log survives.  It reads no harness's name: only what each attempt left.
type call struct {
	l                  *loop
	name, role         string
	model              config.Model
	body, fresh        string // what it is told, and what instead where its conversation will not open
	out, session       string
	findings, previous string // previous: the record file the turn goes on from
	copied             bool   // a reviewer's: each attempt runs where its edits reach nothing
	notice             *run.Object
	checks             *run.Object                         // a builder's: what its done is held to
	handover           func(detail string) (string, error) // the role's next worker, "" for none
	attempts, calls    int                                 // the transient waits spent and the turns run
	lastKill           time.Time
	offered            bool // handover was tried: it is only tried once
	lastSession        string
}

// callFaults are what a turn's ending may be, in Python's order.  Each reads the attempt and goes
// on to the next, or says to go again, or ends the call with its error.
var callFaults = []func(*call, *try) (bool, error){
	(*call).unopened, (*call).neverRan, (*call).harnessWords, (*call).signalled, (*call).silence,
}

// run is the call to the attempt that answered, the attempt's directory holding its records.
func (c *call) run() (*try, error) {
	if !strings.Contains(c.body, foreground) {
		c.body = foreground + "\n\n" + c.body
	}
	c.attempts, c.lastSession = 1, c.session
next:
	for {
		target := c.out
		if c.calls > 0 {
			target = fmt.Sprintf("%s-retry%d", c.out, c.calls)
		}
		t, err := c.attempt(c.body, target)
		if err != nil {
			return nil, err
		}
		c.calls++
		for _, fault := range callFaults {
			again, err := fault(c, t)
			if err != nil {
				return nil, err
			}
			if again {
				continue next
			}
		}
		return t, nil
	}
}

// attempt is one turn in target: no call starts on a stopped run, and whatever it handed in stays
// its own, what a later one on its conversation inherits.
func (c *call) attempt(body, target string) (*try, error) {
	l := c.l
	if err := l.stopCheck(); err != nil {
		return nil, err
	}
	if err := os.MkdirAll(target, 0o777); err != nil {
		return nil, err
	}
	// its time is when a worker last went, which Python's tick reads
	if file, err := os.Create(filepath.Join(l.dir, "launched")); err == nil {
		file.Close()
	}
	previous := ""
	if c.session != "" && c.session == c.lastSession {
		previous = c.previous
	}
	t := &try{out: target, resumed: c.session, asked: c.calls == 0}
	turn := func(cwd string) (failed error) {
		told, at := body, l.workspace
		if cwd != "" {
			told, at = strings.ReplaceAll(told, config.Resolve(l.workspace), cwd), cwd
		}
		t.code, t.session, failed = worker.Turn(c.name, c.role, told, at, target, c.session, worker.Given{
			Context: l.ctx, Efforts: c.model.Efforts, Silence: l.silence, UsersAt: l.usersAt, Checks: c.checks, Findings: c.findings, Previous: previous,
			Env: []string{"AK_RUN_ROLE=worker", "AK_RUN_LOG=" + filepath.Join(l.dir, "log.txt")},
		}, stampedLog{l.dir})
		return failed
	}
	var err error
	if c.copied {
		err = l.place.inCopy(l, target, turn)
	} else {
		err = turn("")
	}
	c.session = cmp.Or(t.session, c.session)
	if kept := l.keepDisputes(target); kept != nil && err == nil {
		err = kept
	}
	var login *worker.LoginExpired
	switch {
	case errors.Is(err, worker.ErrInterrupted):
		return nil, cmp.Or(context.Cause(l.ctx), err)
	case errors.As(err, &login):
		l.say(fmt.Sprintf("%s %s cannot authenticate: %s; the run waits for that login rather than retrying into it", c.role, c.name, login.Why))
		return nil, err
	case errors.Is(err, worker.ErrSilent):
		t.silent = true
	case err != nil:
		return nil, fmt.Errorf("%s %s: %w", c.role, c.name, err)
	}
	t.text = handin.Answer(filepath.Join(target, "final.md"))
	c.previous, c.lastSession = filepath.Join(target, handin.File), c.session
	return t, nil
}

// unopened is a resume the harness says it holds no conversation for, or, of the one the call was
// told to go on, one it ended at once with nothing streamed and nothing answered: retrying that id
// spends the waits on a conversation that will not come back, so the role goes on in a new one,
// Python's resume_failed.
func (c *call) unopened(t *try) (bool, error) {
	if t.resumed == "" || t.silent {
		return false, nil
	}
	if ending, _ := harness.Ending(c.model.Harness, c.said(t), true); ending != harness.Lost &&
		(!t.asked || strings.TrimFunc(t.text, config.Space) != "" || !saidNothing(t.out)) {
		return false, nil
	}
	c.l.say(fmt.Sprintf("resume of %s failed; fresh conversation", t.resumed))
	if c.notice != nil {
		c.notice.Set("restarted", true)
		c.notice.Set("at", clock())
		if err := c.l.save(func(record *run.Object) { record.Set("resume_notice", c.notice) }); err != nil {
			return false, err
		}
	}
	if c.fresh != "" {
		c.body = c.fresh
		if !strings.Contains(c.body, foreground) {
			c.body = foreground + "\n\n" + c.body
		}
	}
	c.session = ""
	return true, nil
}

// neverRan is a harness that says on stderr it never ran the turn, Python's cannot_run: not a wait,
// as no wait installs a harness or logs it in.  A 404 for a model it does not have reads like a 500,
// so this outranks the refusal words.
func (c *call) neverRan(t *try) (bool, error) {
	if t.silent || t.code == 0 || killedWord(t.code) != "" || strings.TrimFunc(t.text, config.Space) != "" {
		return false, nil
	}
	stderr := config.SplitLines(fileTail(filepath.Join(t.out, "stderr.log")))
	line := ""
	if (t.code == 126 || t.code == 127) && saidNothing(t.out) {
		// the shell refused the exec: no wait starts what cannot start, whatever else stderr says
		line = fmt.Sprintf("exited %d with an empty event stream", t.code)
		for _, each := range stderr {
			if words := strings.Fields(each); len(words) > 0 {
				line = strings.Join(words, " ")
				break
			}
		}
	} else if ending, word := harness.Ending(c.model.Harness, strings.Join(stderr, "\n"), false); ending == harness.Fault {
		for _, each := range stderr {
			if harness.Says(each, word) {
				line = strings.Join(strings.Fields(each), " ")
				break
			}
		}
	}
	if line == "" {
		return false, nil
	}
	c.l.say(fmt.Sprintf("WARN %s %s cannot run: %s", c.role, c.name, line))
	return false, &cannotRun{c.name, line}
}

// harnessWords reads what the harness itself said: a spent window goes to another provider, and a
// refusal or an outage is waited out on the same session.  A kill reads as the signal whatever else
// was said, unless the window is spent.
func (c *call) harnessWords(t *try) (bool, error) {
	said := c.said(t)
	ending, mark := harness.Ending(c.model.Harness, said, true)
	if ending == harness.Unsaid || ending != harness.Spent && !t.silent && killedWord(t.code) != "" {
		return false, nil
	}
	message := cmp.Or(said, mark)
	for _, line := range config.SplitLines(said) {
		if harness.Says(line, mark) {
			message = line
			break
		}
	}
	if decoded, err := run.Decode([]byte(message)); err == nil {
		message = cmp.Or(recordText(decoded), message)
	}
	message = cmp.Or(strings.Join(strings.Fields(message), " "), mark)
	if ending != harness.Spent {
		return c.waitOut(fmt.Sprintf("transient %s: %s", quoted(mark), message))
	}
	until := usage.MarkExhausted(c.model.Provider, usage.TryAgainAt(said))
	c.l.say(fmt.Sprintf("WARN %s %s refused: %s; nothing is picked on %s until %s", c.role, c.name, message, c.model.Provider, time.Unix(int64(until), 0).Format("2006-01-02 15:04")))
	return false, &ranDry{mark, t.out, message, t.code}
}

// said is what the harness itself said in the attempt, on a clean exit only its failure events.
func (c *call) said(t *try) string {
	terminal, _ := config.Words(c.model.Harness, "stall", "terminal")
	return harnessSaid(t.out, t.text, strings.Join(terminal, ""), t.code == 0)
}

// signalled is a worker dead by signal, neither on the provider nor on the task: it resumes once, at
// once, and a second kill inside the minute is somebody killing it on purpose, for a person to see.
func (c *call) signalled(t *try) (bool, error) {
	word := killedWord(t.code)
	if t.silent || word == "" {
		return false, nil
	}
	now := time.Now()
	if !c.lastKill.IsZero() && now.Sub(c.lastKill) < killWindow {
		return false, &killedTwice{fmt.Sprintf("%s %s %s twice within a minute; see %s*/stderr.log", c.role, c.name, word, t.out)}
	}
	c.lastKill = now
	c.l.say(fmt.Sprintf("WARN %s %s %s; resuming once%s", c.role, c.name, word, c.resuming()))
	return true, nil
}

// silence is a turn that streamed nothing for the limit, or exited non-zero with nothing to say:
// nothing judged it, so it goes again on the same session.  A final.md the model answered in says
// nothing here, and the attempt that reaches past this answered.
func (c *call) silence(t *try) (bool, error) {
	switch {
	case t.silent:
		return c.waitOut(fmt.Sprintf("emitted no event for %s and was killed with everything it spawned (session %s)", span(c.l.silence), cmp.Or(c.session, "not recorded")))
	case t.code != 0 && strings.TrimFunc(t.text, config.Space) == "":
		return c.waitOut(fmt.Sprintf("exited %d with an empty final.md", t.code))
	}
	return false, nil
}

// waitOut is the road of a transient failure: the second in a row first tries the role's next
// worker, once, and otherwise the growing waits on the same session.
func (c *call) waitOut(why string) (bool, error) {
	if c.handover != nil && c.attempts == 2 && !c.offered {
		c.offered = true
		detail := why + " (twice in a row)"
		next, err := c.handover(detail)
		if err != nil {
			return false, err
		}
		if next != "" {
			return false, &handedOver{c.name, next}
		}
		c.l.say(fmt.Sprintf("WARN %s %s %s; no other worker can take it", c.role, c.name, detail))
	}
	delay := transientDelay(c.attempts)
	c.l.say(fmt.Sprintf("WARN %s %s %s (attempt %d); retrying in %ds%s", c.role, c.name, why, c.attempts, int(delay.Seconds()), c.resuming()))
	c.attempts++
	return true, c.l.wait(delay)
}

// resuming is how a retry's line names the conversation it goes on.
func (c *call) resuming() string {
	if c.session == "" {
		return ""
	}
	return ", resuming session " + c.session
}

// wait sleeps out a wait on something outside the run with its record saying until when, Python's
// run_wait: the tick reads a run's silence off its newest write, and a wait writes nothing.
func (l *loop) wait(delay time.Duration) error {
	if err := l.save(func(record *run.Object) {
		if record.Str("state") == "running" {
			record.Set("transient_wait", run.Fields("until", clock()+delay.Seconds(), "pid", os.Getpid()))
		}
	}); err != nil {
		return err
	}
	select {
	case <-l.ctx.Done():
		return context.Cause(l.ctx)
	case <-time.After(delay):
		return nil
	}
}

// killedWord is how a worker's exit by signal reads, "" for any other exit, which said what its
// code says.
func killedWord(code int) string {
	switch {
	case code >= 0:
		return ""
	case code == -15:
		return "killed (SIGTERM)"
	case code == -9:
		return "killed (SIGKILL)"
	}
	return fmt.Sprintf("killed (SIG%d)", -code)
}

// span is a length of time in the one unit that says the most about it, Python's orch.span.
func span(length time.Duration) string {
	seconds := max(0, int(length.Seconds()))
	for _, unit := range []struct {
		name string
		size int
	}{{"d", 86400}, {"h", 3600}, {"m", 60}} {
		if seconds >= unit.size {
			return fmt.Sprintf("%d%s", seconds/unit.size, unit.name)
		}
	}
	return fmt.Sprintf("%ds", seconds)
}

// saidNothing is whether the harness streamed no event at all.
func saidNothing(out string) bool {
	return strings.TrimFunc(handin.Answer(filepath.Join(out, "events.jsonl")), config.Space) == ""
}
