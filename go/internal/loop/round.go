package loop

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// foreground is what every turn is told of its commands, Python's turns.shell_foreground_note.
var foreground = fmt.Sprintf("Run long commands, tests included, in the foreground and wait for them; a turn that ends with a command still running in the background is not finished. A command that may print nothing for %d minutes starts with `timeout <seconds>`, or that silence stops it.", run.SilenceMinutes)

// step says which step this run is in, since when and in which round, and its seat's bar says it.
func (l *loop) step(name string, more ...any) error {
	seated := ""
	err := l.save(func(record *run.Object) {
		run.SetAll(record, "step", name, "step_at", clock(), "step_round", l.rnd)
		run.SetAll(record, more...)
		seated = run.Seat(record)
	})
	seat.Redress(seated)
	return err
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
// summary once it answered, Python's execute.  A provider that fails or cannot run mid-round does not
// end the round: the turn goes to a model on a provider that refused nothing yet, in a fresh
// directory on a fresh session.  An answer with no closing goes on as if done.  One that says the
// task cannot be done as written ends the run blocked, with nothing to judge.
func (l *loop) execute(word, name, body, findings string) (string, error) {
	turn, err := l.goOn(name, word, body, l.execSession)
	if err != nil {
		return "", err
	}
	l.execSession = turn.session
	if turn.cut != "" {
		if err := l.keepDisputes(turn.cut); err != nil {
			return "", err
		}
	}
	if err := l.step("executor", "verdict", nil, "review", nil, "exec_session", none(l.execSession), "review_session", none(l.reviewSession)); err != nil {
		return "", err
	}
	if err := l.notice(turn); err != nil {
		return "", err
	}
	l.place.beforeTurn(l)
	told, out, previous := turn.body, turn.out, turn.previous
	fresh, shown := "", (*run.Object)(nil)
	if previous != "" { // only a turn whose body was replaced has a conversation that can be refused
		fresh, shown = body, turn.shown
	}
	dry := map[string]bool{}
	handover := func(detail string) (string, error) { return l.handExecutor("transient", detail, dry) }
	for {
		model, err := l.model(l.executor)
		if err != nil {
			return "", err
		}
		if err := l.save(func(record *run.Object) { record.Set("executor_effort", model.TurnEffort(false)) }); err != nil {
			return "", err
		}
		c := &call{l: l, name: l.executor, role: l.place.role(word), model: model, body: told, fresh: fresh, out: out, session: l.execSession,
			findings: findings, previous: previous, notice: shown, handover: handover, checks: l.place.doneChecks(l, word)}
		done, err := c.run()
		var broken *cannotRun
		var refused *ranDry
		var handed *handedOver
		switch {
		case errors.As(err, &handed):
			told = fmt.Sprintf(handoverNote, handed.before) + "\n\n" + body
		case errors.As(err, &broken):
			next, err2 := l.handExecutor("cannot run", broken.detail(), dry)
			if err2 != nil {
				return "", err2
			}
			if next == "" {
				return "", err
			}
			told = body
		case errors.As(err, &refused):
			before := l.executor
			if err := l.saveSession(&l.execSession, c.session, "exec_session"); err != nil {
				return "", err
			}
			next, err2 := l.handExecutor("ran dry", refused.Error(), dry)
			if err2 != nil {
				return "", err2
			}
			if next == "" {
				return "", &exhausted{fmt.Sprintf("%s %s ran dry on %s: %s; no other provider can execute; resume when a meter refills. See %s*/stderr.log", word, before, quoted(refused.mark), refused.Error(), out), true}
			}
			told = fmt.Sprintf(handoverNote, before) + "\n\n" + body
		case err != nil:
			// the parked or killed conversation is on the record before the run parks
			if saved := l.saveSession(&l.execSession, c.session, "exec_session"); saved != nil {
				return "", saved
			}
			return "", err
		default:
			if done.code != 0 {
				l.say(fmt.Sprintf("WARN %s %s; see %s", word, cmp.Or(killedWord(done.code), fmt.Sprintf("exited %d", done.code)), filepath.Join(out, "stderr.log")))
			}
			if err := l.saveSession(&l.execSession, c.session, "exec_session"); err != nil {
				return "", err
			}
			submitted, _ := handin.Read(filepath.Join(done.out, handin.File))
			if err := l.notNeeded(submitted); err != nil {
				return "", err
			}
			return workerResult(done, submitted)
		}
		out = freeDir(l.roundDir(), name+"-"+l.executor)
	}
}

// workerResult is the summary an answered turn leaves, Python's worker_result.
func workerResult(done *try, submitted *handin.Review) (string, error) {
	if submitted != nil && submitted.Closing() != nil && submitted.Closing().Str("kind") == "blocked" {
		why := submitted.Closing().Str("why")
		return "", &blocked{why, "## Blocked\n\n" + why}
	}
	return done.text, nil
}

// saveSession puts the conversation a call left on the loop and the record.
func (l *loop) saveSession(held *string, session, key string) error {
	*held = session
	return l.save(func(record *run.Object) { record.Set(key, none(session)) })
}

// none is a conversation as the record holds it, null before there is one.
func none(session string) any {
	if session == "" {
		return nil
	}
	return session
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
