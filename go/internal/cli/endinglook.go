package cli

import (
	"io"
	"path/filepath"
	"time"

	"agentkit/internal/handback"
	"agentkit/internal/run"
)

// endingLines gives only the launching seat a pointer in its listing or the tick's line
// in its look by id. Neither generating the line nor listing it records a delivery.
func endingLines(entries []listed, caller, wanted string) {
	if caller == "" {
		return
	}
	for i, entry := range entries {
		if run.Seat(entry.record) != caller {
			continue
		}
		if wanted != "" {
			entries[i].ending, entries[i].recordEnding = handback.LookLine(entry.dir, entry.record)
		} else if run.Waits(entry.record) {
			entries[i].ending = "its ending waits for you: ak run status " + entry.name()
		}
	}
}

func (entry listed) stateWord(index run.Index, now time.Time) string {
	if entry.ending != "" {
		return "needs you"
	}
	return run.Word(entry.record, index, now)
}

// printedLook lets the whole display out before recording any ending it told. The terminal
// is measured before buffering, and a buffered caller must flush successfully too.
func printedLook(out io.Writer, text string, entries []listed) error {
	if n, err := io.WriteString(out, text); err != nil {
		return err
	} else if n != len(text) {
		return io.ErrShortWrite
	}
	if buffered, ok := out.(interface{ Flush() error }); ok {
		if err := buffered.Flush(); err != nil {
			return err
		}
	}
	for _, entry := range entries {
		if entry.recordEnding != nil {
			entry.recordEnding()
		}
	}
	return nil
}

func waitEnding(caller, on string, out io.Writer) {
	dir := filepath.Join(run.Runs(), on)
	record, _ := run.Read(dir)
	if record == nil {
		return
	}
	entries := []listed{{dir: dir, record: record}}
	endingLines(entries, caller, on)
	if line := entries[0].ending; line != "" {
		printedLook(out, "  "+line+"\n", entries)
	}
}
