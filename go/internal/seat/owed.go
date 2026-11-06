package seat

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"strings"

	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// OweLine queues a line in Python's format under the send and seat-file locks. The id
// prevents a teller retiring a later copy of the same words after a rename or another teller.
func OweLine(name, line string) error {
	id := make([]byte, 8)
	if _, err := rand.Read(id); err != nil {
		return err
	}
	return notify.Held(context.Background(), name, func(current string) error {
		return changeOwed(current, func(lines []any) []any {
			return append(lines, run.Fields("line", line, "id", hex.EncodeToString(id)))
		})
	})
}

func changeOwed(name string, change func([]any) []any) error {
	path := seatFile(name)
	return put(path, strings.TrimSuffix(path, ".json")+".lock", run.Line, true, func(file *run.Object) bool {
		lines := file.List("owed_lines")
		next := change(lines)
		if run.Equal(lines, next) {
			return false
		}
		var value any
		if len(next) > 0 {
			value = next
		}
		return set([]field{{"owed_lines", value}}, field{"session", name})(file)
	})
}

// A respawn keeps the tmux session's birth but replaces its composer. Invalidate
// receipts before starting that harness; each line and its id remain owed.
// The caller holds the send lock, so an earlier teller's stale check sees the reset.
func retypeOwed(name string) error {
	return changeOwed(name, func(lines []any) []any {
		next := append([]any(nil), lines...)
		for i, value := range next {
			if line, ok := value.(*run.Object); ok && line.Has("typed") {
				clean := line.Copy()
				clean.Delete("typed")
				next[i] = clean
			}
		}
		return next
	})
}

// owedReadable leaves account moves and editor receipts to Python.
func owedReadable(file *run.Object) bool {
	if file == nil || !file.Truthy("owed_lines") {
		return true
	}
	lines, listed := file.Get("owed_lines").([]any)
	if !listed {
		return false
	}
	for _, value := range lines {
		line, ok := value.(*run.Object)
		if !ok || line.Str("line") == "" || !only(line, []string{"id", "line", "typed"}) {
			return false
		}
		if line.Truthy("typed") && (line.Dict("typed") == nil || !only(line.Dict("typed"), []string{"line", "seat"})) {
			return false
		}
	}
	return true
}

// A slow startup's unknown screen adds no interrupted turn to a continuation
// already owed. That queue still belongs to ak after its next reopen.
func continuationQueued(file *run.Object) bool {
	return file != nil && file.Truthy("owed_lines") && owedReadable(file)
}

// TellOwed keeps the first line until its confirmed send, however late the prompt shows.
// Both the receipt and each key are conditional on that same line still heading the queue.
func TellOwed(name string, log func(string)) (bool, error) {
	file, _ := run.ReadJSON(seatFile(name))
	if !owedReadable(file) {
		return false, nil
	}
	if file == nil || len(file.List("owed_lines")) == 0 || !Watching(name) {
		return true, nil
	}
	read := file.List("owed_lines")[0].(*run.Object)
	replace := func(current string, next ...any) error {
		return changeOwed(current, func(lines []any) []any {
			if len(lines) == 0 || !run.Equal(lines[0], read) {
				return lines
			}
			return append(next, lines[1:]...)
		})
	}
	stale := func(current string) bool {
		name = current
		file, _ := run.ReadJSON(seatFile(current))
		return file == nil || len(file.List("owed_lines")) == 0 || !run.Equal(file.List("owed_lines")[0], read)
	}
	var receiptErr error
	sent := typeAtPrompt(name, read.Str("line"), read.Dict("typed"), func(mark *run.Object) error {
		next := read.Copy()
		next.Set("typed", mark)
		receiptErr = replace(name, next)
		read = next
		return receiptErr
	}, log, stale)
	if !sent {
		return true, receiptErr
	}
	err := notify.Held(context.Background(), name, func(current string) error { return replace(current) })
	if err == nil {
		log("told " + name + ": " + read.Str("line"))
	}
	return true, err
}

// TypeAtPrompt types a line into that seat at its quiet prompt, a line its mark `typed` says is
// in the composer already getting only its Enter; `receipt` keeps the mark of one typed now.
func TypeAtPrompt(name, line string, typed *run.Object, receipt func(*run.Object) error, log func(string)) bool {
	return typeAtPrompt(name, line, typed, receipt, log, func(string) bool { return false })
}

// A receipt gets only its Enter, or confirmation of an empty composer, on later ticks.
func (at seatAt) finishTyped(line string, stale func(string) bool, log func(string)) bool {
	delivered := false
	notify.Held(context.Background(), at.name, func(current string) error {
		at.name = current
		if stale(current) {
			return nil
		}
		switch at.holds(line) {
		case "empty":
			delivered = !at.unread()
		case "line":
			at.enter(log)
		}
		return nil
	})
	return delivered
}
