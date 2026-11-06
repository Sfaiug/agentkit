package loop

import (
	"agentkit/internal/handin"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

type notNeeded struct{ why string }

func (n *notNeeded) Error() string { return n.why }

// Only a fix run's first turn may find the defect already gone (roundloop.worker_result).
func (l *loop) notNeeded(submitted *handin.Review) error {
	if submitted == nil || submitted.Closing() == nil || submitted.Closing().Str("kind") != "not-needed" {
		return nil
	}
	record, _ := run.Read(l.dir)
	if record != nil && len(record.List("round_summaries")) == 0 && l.fixRun(record) {
		return &notNeeded{submitted.Closing().Str("why")}
	}
	return nil
}

// fixRun is whether the run was launched to make a given failing command pass, Python's
// Loop.fix_run: its record holds a follow-up, or its task the fix words.
func (l *loop) fixRun(record *run.Object) bool {
	return record.Truthy("followup") || task.IsFix(l.body)
}

func (l *loop) finishNotNeeded(ending *notNeeded) error {
	return write(l.dir, func(record *run.Object) {
		run.SetAll(record, "state", "not_needed", "verdict", nil, "not_needed", ending.why, "finished_at", clock())
	})
}
