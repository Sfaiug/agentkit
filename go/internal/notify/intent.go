package notify

import (
	"crypto/sha256"
	"encoding/hex"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/run"
)

// An intent is the dones row a seat's done writes in history.db (notify._intent): the done in its
// conversation, where the owner's intent it ends began, the runs the seat started for it, and the
// seat's finished work.
type intent struct {
	conversation string
	at           float64
	began        any
	runs         []string
	work         string
}

// intentOf is the row the seat's done writes now, read before the card's files are written, its
// finished work the plan's ticked lines and the runs it launched that merged; nil where it writes
// none, and an error where Go does not read it as Python does.
func intentOf(name string, ticked []any) (*intent, error) {
	conversation, messages, err := OwnerMessages(name)
	if err != nil || conversation == "" {
		return nil, err
	}
	done := &intent{conversation: config.SeatHarness(name) + ":" + conversation, at: clock()}
	type started struct {
		id string
		at float64
	}
	var mine []started
	merged, seats, smoke := []any{}, run.Seats(), run.Smoke()
	// menu.run_records' runs, in its order
	if !run.Every(func(dir string, record *run.Object) bool {
		if !record.Truthy("unattended") && !smoke(record) && seats(record) == name {
			if record.Truthy("merged") {
				merged = append(merged, filepath.Base(dir))
			}
			mine = append(mine, started{filepath.Base(dir), number(record, "started_at")})
		}
		return true
	}) {
		return nil, ErrUnread
	}
	sum := sha256.Sum256([]byte(run.Line([]any{ticked, merged})))
	done.work = hex.EncodeToString(sum[:])
	last, err := history.LastDone(done.conversation)
	if err != nil {
		return nil, err
	}
	previous, before := last.Num("last")
	since, _ := last.Num("since")
	var asked, fresh []float64
	for _, message := range messages {
		if message.At <= done.at {
			asked = append(asked, message.At)
			if !before || message.At > previous {
				fresh = append(fresh, message.At)
			}
		}
	}
	// The start is unknown, and the done still the next one's boundary: with no message of the
	// owner's since, for a conversation's first done begun before dones were kept, and for the
	// finished work its previous done recorded, as an answer about finished work finished nothing.
	if len(fresh) == 0 || !before && slices.Min(asked) < since || last.Text("work") == done.work {
		return done, nil
	}
	began := slices.Min(fresh)
	done.began = began
	for _, each := range mine {
		if began <= each.at && each.at <= done.at {
			done.runs = append(done.runs, each.id)
		}
	}
	return done, nil
}

// record writes the row, none for no intent.
func (done *intent) record() {
	if done != nil {
		history.Done(done.conversation, done.at, done.began, done.runs, done.work)
	}
}
