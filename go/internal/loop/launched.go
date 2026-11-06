package loop

import (
	"fmt"

	"agentkit/internal/run"
)

// sayLaunched is the one line a launch from a seat puts on the seat's terminal once its pair is
// picked, Python's launch_line: where the run counts, and that the seat is told when it ends.  The
// driver's log is that terminal, which the foreground follows, as Python's child's stdout is its log.
func (l *loop) sayLaunched() {
	record, _ := run.Read(l.dir)
	if record == nil || run.Seat(record) == "" {
		return
	}
	models := l.executor + "/" + l.reviewer
	if l.executor == "" {
		models = l.reviewer + " review" // a review-only run names its reviewer alone
	}
	if run.SelfReviewed(record, run.Models()) {
		models += ", self-reviewed"
	}
	appendLog(l.dir, fmt.Sprintf("run %s launched: %s (%s); it counts on this bar and in the menu; you will be told when it ends\n",
		l.id, record.Str("title"), models))
}
