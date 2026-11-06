package loop

import (
	"fmt"
	"path/filepath"

	"agentkit/internal/handin"
)

// answered is the out directory of the round's latest executor or fixer turn where it closed,
// Python's saved_worker_answer, "" where that turn is still open or none began.
func answered(round string) string {
	name := latestWorker(round)
	if name == "" {
		return ""
	}
	if kind, _ := openTurn(round, name); kind != "" {
		return ""
	}
	return latestTurn(round, name)
}

// goOnAnswered is the summary of the turn at out, which answered before its round's checks ended,
// Python's continuation `done-when`: what it handed in stands, so no turn is spent on it again, and
// the checks run again.
func (l *loop) goOnAnswered(out string) (string, error) {
	l.say(fmt.Sprintf("--- round %d/%d: continuing done-when", l.rnd, l.budget))
	submitted, _ := handin.Read(filepath.Join(out, handin.File))
	if err := l.notNeeded(submitted); err != nil {
		return "", err
	}
	return workerResult(&try{text: handin.Answer(filepath.Join(out, "final.md"))}, submitted)
}
