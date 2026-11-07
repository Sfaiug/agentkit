package seat

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// OweLine queues a line in Python's format under the send and seat-file locks.
func OweLine(name, line string) error {
	return notify.Held(context.Background(), name, func(current string) error {
		return oweLines(current, run.Fields("line", line))
	})
}

// oweLines adds those lines to what the seat is owed, as watch.owe_line does under the send lock
// its caller holds: a move's (`switch`) ahead of all but those begun or of an earlier move, any
// other last.  Each takes an id, so a teller retiring the line it told never retires a later copy
// of the same words after a rename or another teller.
func oweLines(name string, owed ...*run.Object) error {
	added := make([]any, len(owed))
	for at, line := range owed {
		id := make([]byte, 8)
		if _, err := rand.Read(id); err != nil {
			return err
		}
		line = line.Copy()
		line.Set("id", hex.EncodeToString(id))
		added[at] = line
	}
	return changeOwed(name, func(lines []any) []any {
		next := slices.Clone(lines)
		for _, line := range added {
			at := len(next)
			if line.(*run.Object).Truthy("switch") {
				if ahead := slices.IndexFunc(next, func(value any) bool {
					old, _ := value.(*run.Object)
					return old == nil || !old.Truthy("switch") && !old.Truthy("typed")
				}); ahead >= 0 {
					at = ahead
				}
			}
			next = slices.Insert(next, at, line)
		}
		return next
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

// owedReadable leaves editor receipts, and any key it does not know, to Python; a move's line
// (`switch`) names the pane it goes to.
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
		if !ok || line.Str("line") == "" || !only(line, []string{"id", "line", "typed", "switch", "pane"}) {
			return false
		}
		if line.Truthy("typed") && (line.Dict("typed") == nil || !only(line.Dict("typed"), []string{"line", "seat", "pid"})) {
			return false
		}
	}
	return true
}

// A slow startup's unknown screen adds no interrupted turn to a continuation
// already owed. That queue still belongs to ak after its next reopen; a move's
// line (`switch`) is none, and the launch retires it.
func continuationQueued(file *run.Object) bool {
	return file != nil && owedReadable(file) && slices.ContainsFunc(file.List("owed_lines"), func(line any) bool {
		return !line.(*run.Object).Truthy("switch")
	})
}

// TellOwed keeps the first line until its confirmed send, however late the prompt shows.
// Both the receipt and each key are conditional on that same line still heading the queue.  A
// line goes to the pane it names, and a move's begins no turn: the next goes in at the same
// prompt, its harness's answers counted from the moment it went in (`switched`).
func TellOwed(name string, log func(string)) (bool, error) {
	file, _ := run.ReadJSON(seatFile(name))
	if !owedReadable(file) || movesUntyped(name, file) {
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
	sent := typeAtPane(name, read.Str("pane"), read.Str("line"), read.Dict("typed"), func(mark *run.Object) error {
		next := read.Copy()
		next.Set("typed", mark)
		receiptErr = replace(name, next)
		read = next
		return receiptErr
	}, log, stale)
	if !sent {
		return true, receiptErr
	}
	if read.Truthy("switch") { // written before its line is no longer owed
		if err := writeSeat(filepath.Join(config.Home(), "state"), name, []field{{"switched", seconds(time.Now())}}); err != nil {
			return true, err
		}
	}
	err := notify.Held(context.Background(), name, func(current string) error { return replace(current) })
	if err != nil {
		return true, err
	}
	log("told " + name + ": " + read.Str("line"))
	if read.Truthy("switch") {
		return TellOwed(name, log)
	}
	return true, nil
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
