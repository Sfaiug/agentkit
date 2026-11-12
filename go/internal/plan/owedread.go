package plan

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// answers are what this process's asks answered, by the file each goes in, until KeepAnswers
// writes them there as its command ends: a later ask here answers from one as from that file.
var answers = struct {
	sync.Mutex
	by map[string]answer
}{by: map[string]answer{}}

// An answer is whether a seat owes its done check, as an ask that read so (asked) answered.
type answer struct {
	read string
	owes bool
}

// writes tells apart the writes of this process's answers, as Python's thread does its own.
var writes atomic.Int64

// asked is what checkOwed answers from short of the owner's words, as a digest (done_check.asked):
// the plan's lines, what a check kept, the conversations had of the seat that goes by current, as
// notify.Listed gives them, and each file read for them with its identity, size and modification
// time: the seat's typing receipts, which tell ak's lines in it from the owner's, each
// conversation's own file by each of its names, and Go's own program, which an update replaces.
// Python stamps its code's folders there, so neither takes an answer the other read: each reads
// again after the other wrote.  Taken before any word is read, so a file written meanwhile reads
// changed next time.  "" where a conversation's harness keeps it in no file of its own Go names
// (harness.FiledIn), or Go stamps no file here: each ask reads it.
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

// answered is the answer an ask that read the same (asked) made in this process or kept at path
// (done_check.answered), false for none.
func answered(path, read string) (owes, kept bool) {
	if read == "" {
		return false, false
	}
	answers.Lock()
	made, ok := answers.by[path]
	answers.Unlock()
	if ok && made.read == read {
		return made.owes, true
	}
	was, _ := run.ReadJSON(path)
	if was == nil || was.Get("read") != read {
		return false, false
	}
	owes, kept = was.Get("owed").(bool)
	return owes, kept
}

// keepAnswer holds what an ask that read so answered, where it has a digest, for KeepAnswers to
// write at path.
func keepAnswer(path, read string, owes bool) {
	if read == "" {
		return
	}
	answers.Lock()
	answers.by[path] = answer{read, owes}
	answers.Unlock()
}

// KeepAnswers writes down, as a command ends, each answer its asks made, where carried: none for a
// command handed over or run dry, which leaves its case to Python with nothing written.  Each
// whole, by a name of this process's own, so of two at once either may stand; a state ak cannot
// write here leaves the next ask to read again.  The process then holds none, as the next command
// starts.
func KeepAnswers(carried bool) {
	answers.Lock()
	made := answers.by
	answers.by = map[string]answer{}
	answers.Unlock()
	if !carried {
		return
	}
	for path, was := range made {
		fresh := fmt.Sprintf("%s.%d.%d", path, os.Getpid(), writes.Add(1))
		if os.WriteFile(fresh, []byte(run.Line(run.Fields("read", was.read, "owed", was.owes))+"\n"), 0o666) == nil {
			os.Rename(fresh, path)
		}
	}
}
