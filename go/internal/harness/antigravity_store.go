package harness

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"
	"unicode/utf8"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/sqlite"
)

// agyInput is the `steps.step_type` of a user input (antigravity.py `USER`).
const agyInput = 14

// Each kind of step keeps its words in its payload under two fields: a user input's text, and a
// planner response's answer, its thinking and tool calls beside that (antigravity.py `said`).
var agyWords = map[int64]struct {
	who         string
	step, words uint64
}{agyInput: {"user", 19, 2}, agyAnswer: {"model", 20, 1}}

// An agyStep is one user input, answer or question card of a conversation: its kind, and its
// metadata and payload where they are blobs, as only a blob is a message.
type agyStep struct {
	kind              int64
	metadata, payload []byte
}

// antigravityStore is where agy keeps that conversation, a SQLite database of its own; "" for an
// id that names no file of its own.
func antigravityStore(conversation string) string {
	if !antigravityConversation.MatchString(conversation) {
		return ""
	}
	return filepath.Join(antigravityConversations(), conversation+".db")
}

// antigravityConversations is the folder agy keeps every login's conversations in.
func antigravityConversations() string {
	return filepath.Join(config.UserHome(), ".gemini", "antigravity-cli", "conversations")
}

// antigravitySaid is that conversation as agy shows it, oldest first (antigravityWords), read
// loosely, as questions.unseen reads it: a store that cannot be read shows nothing.
func antigravitySaid(conversation string) []Turn {
	said, _, _ := antigravityWords(conversation)
	return said
}

// antigravityTyped is each user input of that conversation, dated by its step's metadata, field
// 1 a Timestamp; a step dated otherwise is nobody's answer (antigravity.py `user_messages`).  The
// error where its store is there and cannot be read (antigravitySteps).
func antigravityTyped(conversation string) (typed []Prompt, _ error) {
	var read agyReading
	steps, err := antigravitySteps(conversation)
	for _, step := range steps {
		at, dated := read.timestamp(read.field(step.metadata, 1))
		if text := step.words(); step.kind == agyInput && dated && text != "" {
			typed = append(typed, Prompt{at, text})
		}
	}
	return typed, err
}

// antigravitySteps is each user input, answer and question card of that conversation, in order,
// read from its store as Python's harness.rows reads a harness's own: read-only, its write-ahead
// log included; none where there is none.  The error where it is there and Python's sqlite3
// cannot read it, which `rows` raises reading strictly (harness.unread).
func antigravitySteps(conversation string) ([]agyStep, error) {
	path := antigravityStore(conversation)
	if path == "" {
		return nil, nil
	}
	unread := func(err error) error { return fmt.Errorf("cannot read %s: %w", path, err) }
	if info, err := os.Stat(path); errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	} else if err != nil {
		return nil, unread(err)
	} else if !info.Mode().IsRegular() { // Python's sqlite3 fails on it; a pipe would hang the open
		return nil, unread(errors.New("not a file"))
	}
	conn, err := sqlite.Open(path, sqlite3.OPEN_READONLY)
	if err != nil {
		return nil, unread(err)
	}
	defer conn.Close()
	conn.BusyTimeout(5 * time.Second) // sqlite3.connect's own
	stmt, _, err := conn.Prepare("SELECT step_type, metadata, step_payload FROM steps WHERE step_type IN (?, ?, ?) ORDER BY idx")
	if err != nil {
		return nil, unread(err)
	}
	defer stmt.Close()
	if err := errors.Join(stmt.BindInt(1, agyInput), stmt.BindInt(2, agyAnswer), stmt.BindInt(3, agyCard)); err != nil {
		return nil, unread(err)
	}
	var steps []agyStep
	for stmt.Step() {
		row := make([]any, 3)
		if err := stmt.Columns(row...); err != nil {
			return nil, unread(err)
		}
		for _, value := range row {
			if text, isText := value.(string); isText && !utf8.ValidString(text) { // Python's sqlite3 raises
				return nil, unread(errors.New("a value that is not UTF-8"))
			}
		}
		kind, _ := row[0].(int64)
		metadata, _ := row[1].([]byte)
		payload, _ := row[2].([]byte)
		steps = append(steps, agyStep{kind, metadata, payload})
	}
	if err := stmt.Err(); err != nil {
		return nil, unread(err)
	}
	return steps, nil
}

// words is what a user input or answer says, "" for none and for any other step; agy writes them
// as protocol buffer strings, read as Python decodes them.
func (step agyStep) words() string {
	var read agyReading
	words, said := agyWords[step.kind]
	if !said {
		return ""
	}
	return gitcall.Decoded(string(read.field(read.field(step.payload, words.step), words.words)))
}
