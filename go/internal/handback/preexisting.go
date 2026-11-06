package handback

import (
	"context"
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// MarkHistory marks every unheard ending over an hour old handed back without replaying it, in one
// line naming them, as Python's sweep_preexisting: nothing is typed and nothing reopened.  An
// ending already seen, waiting for a seat or a card, is not history.  False at a record Go cannot
// read as Python does, what it marked before standing.
func MarkHistory(say func(string)) bool {
	at := now()
	var marked []string
	read := run.Every(func(dir string, record *run.Object) bool {
		if !unheard(record) {
			return true
		}
		held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
		if err != nil {
			return true
		}
		defer held.Close()
		current, _ := run.Read(dir)
		if current != nil && unheard(current) && mark(dir, current, "handed_back", at, "handback_note", preexisting, "handback_pending", nil) {
			marked = append(marked, filepath.Base(dir))
		}
		return true
	})
	if len(marked) > 0 {
		sort.Strings(marked)
		say(fmt.Sprintf("marked %d pre-existing endings as handed back without replaying (%s): %s",
			len(marked), preexisting, strings.Join(marked, ", ")))
	}
	return read
}

// unheard is an ending owed and never seen, too old to replay.
func unheard(record *run.Object) bool {
	return Owed(record, time.Now()) && !record.Truthy("handback_pending") && !record.Truthy("notification_pending") && history(record)
}
