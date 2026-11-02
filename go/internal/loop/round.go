package loop

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
	"agentkit/internal/worker"
)

// foreground is what every turn is told of its commands, Python's turns.shell_foreground_note.
var foreground = fmt.Sprintf("Run long commands, tests included, in the foreground and wait for them; a turn that ends with a command still running in the background is not finished. A command that may print nothing for %d minutes starts with `timeout <seconds>`, or that silence stops it.", run.SilenceMinutes)

// roundName is the one round a run takes here: any other is a fixer's.
const roundName = "round-1"

// round is the executor's turn, the checks and the reviewer's verdict, Python's rounds on a run
// that passes in its first.
func (l *loop) round() error {
	var rounds int
	if err := l.save(func(record *run.Object) { rounds, _ = record.Int("rounds") }); err != nil {
		return err
	}
	l.say(fmt.Sprintf("--- round 1/%d: executor %s", rounds, l.executor))
	summary, err := l.execute()
	if err != nil {
		return err
	}
	// a change past the ceiling is refused now, before its checks
	if err := l.place.worked(l); err != nil {
		return err
	}
	text, err := l.verify()
	if err != nil {
		return err
	}
	if err := l.place.beforeReview(l); err != nil {
		return err
	}
	return l.review(summary, text)
}

// step says which step this run is in, since when and in which round.
func (l *loop) step(name string, more ...any) error {
	return l.save(func(record *run.Object) {
		run.SetAll(record, "step", name, "step_at", clock(), "step_round", 1)
		run.SetAll(record, more...)
	})
}

// model is a model as this run runs it: at the efforts it launched with, later edits aside.
func (l *loop) model(name string) (config.Model, error) {
	model, err := config.ModelNamed(name)
	if err != nil {
		return model, err
	}
	if l.efforts != nil {
		if held := l.efforts.Dict(name); held != nil {
			model.Efforts = map[string]string{}
			for _, key := range held.Keys() {
				model.Efforts[key] = held.Str(key)
			}
		}
	}
	return model, nil
}

// execute is the executor's turn, its summary once it closed: one that says the task cannot be
// done as written ends the run blocked, with nothing to judge.
func (l *loop) execute() (string, error) {
	model, err := l.model(l.executor)
	if err != nil {
		return "", err
	}
	if err := l.step("executor", "verdict", nil, "review", nil, "exec_session", nil, "review_session", nil,
		"executor_effort", model.TurnEffort(false)); err != nil {
		return "", err
	}
	l.place.beforeTurn(l)
	out := filepath.Join(l.dir, roundName, "executor")
	session, err := l.turn(l.workspace, l.executor, model, "executor", l.place.role("executor"), l.prompt, out)
	if err != nil {
		return "", err
	}
	if err := l.save(func(record *run.Object) { record.Set("exec_session", session) }); err != nil {
		return "", err
	}
	submitted, _ := handin.Read(filepath.Join(out, handin.File))
	if submitted == nil || submitted.Closing() == nil {
		return "", notYet(fmt.Sprintf("executor %s gave no closing; see %s", l.executor, filepath.Join(out, "stderr.log")), "a silent turn")
	}
	if closing := submitted.Closing(); closing.Str("kind") == "blocked" {
		why := closing.Str("why")
		return "", &blocked{why, "## Blocked\n\n" + why}
	}
	return handin.Answer(filepath.Join(out, "final.md")), nil
}

// turn runs one turn of the model from cwd in its out directory, the conversation it leaves once it
// ended well enough to read: any other ending is a road Go does not carry out.
func (l *loop) turn(cwd, name string, model config.Model, word, role, body, out string) (string, error) {
	if err := l.stopCheck(); err != nil {
		return "", err
	}
	if !strings.Contains(body, foreground) {
		body = foreground + "\n\n" + body
	}
	if err := os.MkdirAll(out, 0o777); err != nil {
		return "", err
	}
	// its time is when a worker last went, which Python's tick reads
	if file, err := os.Create(filepath.Join(l.dir, "launched")); err == nil {
		file.Close()
	}
	who := word + " " + name
	code, session, err := worker.Turn(name, role, body, cwd, out, "", worker.Given{
		Context: l.ctx, Efforts: model.Efforts, Silence: l.silence, UsersAt: l.usersAt, ReviewLines: l.reviewLines,
		Env: []string{"AK_RUN_ROLE=worker", "AK_RUN_LOG=" + filepath.Join(l.dir, "log.txt")},
	}, stampedLog{l.dir})
	stderr := filepath.Join(out, "stderr.log")
	var login *worker.LoginExpired
	switch {
	case errors.Is(err, worker.ErrInterrupted):
		return "", context.Cause(l.ctx)
	case errors.Is(err, worker.ErrSilent):
		return "", notYet(fmt.Sprintf("%s emitted no event for %g min and was stopped; see %s", who, l.silence.Minutes(), stderr), "a silent turn")
	case errors.As(err, &login):
		return "", notYet(login.Error(), "a login to renew")
	case err != nil:
		return "", notYet(who+": "+err.Error(), "a failed turn")
	case code != 0:
		return "", notYet(fmt.Sprintf("%s exited %d; see %s", who, code, stderr), "a failed or exhausted turn")
	case unfinished(out):
		return "", notYet(who+" ended its turn with a command still in the background", "finishing it in the foreground")
	}
	return session, nil
}

// unfinished is whether a turn ended with a command still running, Python's worker.turn and
// turn_unfinished: its box stopped one, or its harness says so on stderr or in the last list of
// background tasks it streamed.  A file missing or unreadable is no signal.
func unfinished(out string) bool {
	if data, err := os.ReadFile(filepath.Join(out, "box-processes.json")); err == nil {
		var report struct{ Processes []any }
		if json.Unmarshal(data, &report) == nil && len(report.Processes) > 0 {
			return true
		}
	}
	if strings.Contains(handin.Answer(filepath.Join(out, "stderr.log")), "Background tasks still running") {
		return true
	}
	tasks := false
	for _, line := range strings.Split(handin.Answer(filepath.Join(out, "events.jsonl")), "\n") {
		value, _ := run.Decode([]byte(line))
		if event, _ := value.(*run.Object); event != nil && event.Str("subtype") == "background_tasks_changed" {
			tasks = len(event.List("tasks")) > 0
		}
	}
	return tasks
}

// verify is the checks of the round on what the workplace holds, what they said once all exited 0:
// a failure's fixer turn is a road Go does not carry out.
func (l *loop) verify() (string, error) {
	if err := l.step("done-when"); err != nil {
		return "", err
	}
	ok, text, err := l.place.verify(l, filepath.Join(l.dir, roundName, "donewhen.log"))
	if err != nil {
		return "", err
	}
	if !ok {
		l.say("done-when: FAILED")
		return "", notYet("the done-when failed: "+failing(text), "its fixer turn")
	}
	l.say("done-when: all passed")
	return text, l.save(func(record *run.Object) {
		record.Set("done_when_failure", run.Fields("every", []any{}))
		if !record.Has("artifacts") {
			record.Set("artifacts", []any{})
		}
	})
}
