package plan

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sync/atomic"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// writes tells apart the writes of this process's asks, as Python's thread does its own.
var writes atomic.Int64

// asked is what checkOwed answers from short of the owner's words, as a digest (done_check.asked):
// the plan's lines, what a check kept, the conversations had of the seat that goes by current, as
// notify.Listed gives them, and each file read for them with its identity, size and modification
// time: the seat's typing receipts, which tell ak's lines in it from the owner's, each
// conversation's own file by each of its names, and Go's own program, which an update replaces.
// Python stamps its code's folders there, so neither takes an answer the other read: each reads
// again after the other wrote.  Taken before any word is read, so a file written meanwhile reads
// changed next time.  "" where a conversation's harness keeps it in no file of its own Go names
// (harness.FiledIn), or Go stamps no file here: each ask reads it; "" too where the seat has no
// conversation, so an ask that reads nothing writes nothing.
func asked(current string, had []notify.Conversation, lines []string, kept any) (string, error) {
	program, err := os.Executable()
	if err == nil {
		program, err = filepath.EvalSymlinks(program)
	}
	if err != nil {
		return "", nil
	}
	files := []string{filepath.Join(config.Home(), "state", config.SeatFileNames(current)["input"]), program}
	conversations := []any{}
	for _, each := range had {
		conversation, names, filed := harness.FiledIn(each.Harness, each.Record)
		switch {
		case !filed:
			return "", nil
		case conversation != "": // a current one its record names none of is none (conversations_of)
			conversations = append(conversations, []any{each.Harness, conversation})
			files = append(files, names...)
		}
	}
	if len(conversations) == 0 {
		return "", nil // nothing to read, so nothing a kept answer would spare
	}
	stamps := []any{}
	for _, file := range files {
		stamp, stamped, err := harness.Stamp(file)
		switch {
		case err != nil:
			return "", err
		case !stamped:
			return "", nil
		case stamp == nil:
			stamp = []any{nil}
		}
		stamps = append(stamps, append([]any{file}, stamp...))
	}
	text := []any{}
	for _, line := range lines {
		text = append(text, line)
	}
	sum := sha256.Sum256([]byte(run.Line([]any{text, kept, conversations, stamps})))
	return hex.EncodeToString(sum[:]), nil
}

// answered is the answer an ask that read the same (asked) kept at path (done_check.answered),
// false for none.
func answered(path, read string) (owes, kept bool) {
	if read == "" {
		return false, false
	}
	was, _ := run.ReadJSON(path)
	if was == nil || was.Get("read") != read {
		return false, false
	}
	owes, kept = was.Get("owed").(bool)
	return owes, kept
}

// keepAnswer keeps at path what an ask that read so answered, where it has a digest: whole, by a
// name of this ask's own, so of two asks at once either may stand.  A state ak cannot write here
// leaves the next ask to read again.
func keepAnswer(path, read string, owes bool) {
	if read == "" {
		return
	}
	fresh := fmt.Sprintf("%s.%d.%d", path, os.Getpid(), writes.Add(1))
	if os.WriteFile(fresh, []byte(run.Line(run.Fields("read", read, "owed", owes))+"\n"), 0o666) == nil {
		os.Rename(fresh, path)
	}
}
