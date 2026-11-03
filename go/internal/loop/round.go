package loop

import (
	"cmp"
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

// step says which step this run is in, since when and in which round.
func (l *loop) step(name string, more ...any) error {
	return l.save(func(record *run.Object) {
		run.SetAll(record, "step", name, "step_at", clock(), "step_round", l.rnd)
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

// execute is one turn of the round's executor under the name given (executor or fixer, word its
// rules, name its directory), resuming its conversation, handed the findings file if any: its
// summary once it closed.  One that says the task cannot be done as written ends the run blocked,
// with nothing to judge.
func (l *loop) execute(word, name, body, findings string) (string, error) {
	model, err := l.model(l.executor)
	if err != nil {
		return "", err
	}
	ask, err := l.goOn(name, word, body, l.execSession)
	if err != nil {
		return "", err
	}
	l.execSession = ask.session
	if ask.cut != "" {
		if err := l.keepDisputes(ask.cut); err != nil {
			return "", err
		}
	}
	if err := l.step("executor", "verdict", nil, "review", nil, "exec_session", none(l.execSession), "review_session", none(l.reviewSession),
		"executor_effort", model.TurnEffort(false)); err != nil {
		return "", err
	}
	if err := l.notice(ask); err != nil {
		return "", err
	}
	l.place.beforeTurn(l)
	session, failed := l.turn(l.workspace, l.executor, model, word, l.place.role(word), ask.body, ask.out, ask.session, findings, ask.previous)
	out := ask.out
	if err := l.keepDisputes(out); failed == nil {
		failed = err
	}
	if failed != nil {
		return "", failed
	}
	if session != "" {
		l.execSession = session
	}
	if err := l.save(func(record *run.Object) { record.Set("exec_session", none(l.execSession)) }); err != nil {
		return "", err
	}
	submitted, _ := handin.Read(filepath.Join(out, handin.File))
	if submitted == nil || submitted.Closing() == nil {
		return "", notYet(fmt.Sprintf("%s %s gave no closing; see %s", word, l.executor, filepath.Join(out, "stderr.log")), "a silent turn")
	}
	if closing := submitted.Closing(); closing.Str("kind") == "blocked" {
		why := closing.Str("why")
		return "", &blocked{why, "## Blocked\n\n" + why}
	}
	return handin.Answer(filepath.Join(out, "final.md")), nil
}

// none is a conversation as the record holds it, null before there is one.
func none(session string) any {
	if session == "" {
		return nil
	}
	return session
}

// An exited is a turn whose harness exited non-zero, which only a reviewer's verdict outlives.
type exited struct {
	code int
	err  error
}

func (e *exited) Error() string { return e.err.Error() }

// turn runs one turn of the model from cwd in its out directory on that conversation, the
// conversation it leaves once it ended well enough to read: any other ending is a road Go does not
// carry out.
func (l *loop) turn(cwd, name string, model config.Model, word, role, body, out, session, findings, previous string) (string, error) {
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
	code, left, err := worker.Turn(name, role, body, cwd, out, session, worker.Given{
		Context: l.ctx, Efforts: model.Efforts, Silence: l.silence, UsersAt: l.usersAt, ReviewLines: l.reviewLines, Findings: findings, Previous: previous,
		Env: []string{"AK_RUN_ROLE=worker", "AK_RUN_LOG=" + filepath.Join(l.dir, "log.txt")},
	}, stampedLog{l.dir})
	stderr := filepath.Join(out, "stderr.log")
	var login *worker.LoginExpired
	switch {
	case errors.Is(err, worker.ErrInterrupted):
		return "", cmp.Or(context.Cause(l.ctx), err)
	case errors.Is(err, worker.ErrSilent):
		return "", notYet(fmt.Sprintf("%s emitted no event for %g min and was stopped; see %s", who, l.silence.Minutes(), stderr), "a silent turn")
	case errors.As(err, &login):
		return "", notYet(login.Error(), "a login to renew")
	case err != nil:
		return "", notYet(who+": "+err.Error(), "a failed turn")
	case code != 0:
		return left, &exited{code, notYet(fmt.Sprintf("%s exited %d; see %s", who, code, stderr), "a failed or exhausted turn")}
	case unfinished(out):
		return "", notYet(who+" ended its turn with a command still in the background", "finishing it in the foreground")
	}
	return left, nil
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

// verify is the checks of the round on what the workplace holds: whether they passed, what they said.
func (l *loop) verify() (bool, string, error) {
	if err := l.step("done-when"); err != nil {
		return false, "", err
	}
	ok, text, err := l.place.verify(l, filepath.Join(l.roundDir(), "donewhen.log"))
	if err != nil {
		return false, "", err
	}
	return ok, text, l.save(func(record *run.Object) {
		if !record.Has("artifacts") {
			record.Set("artifacts", []any{})
		}
	})
}
