package harness

import (
	"path/filepath"
	"strings"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/config"
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

// An agyStep is one user input or answer of a conversation: its kind, and its metadata and
// payload where they are blobs, as only a blob is a message.
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

// antigravitySaid is that conversation as agy shows it, oldest first: each user input and
// answer with words in it (antigravity.py `said`).
func antigravitySaid(conversation string) (said []Turn) {
	for _, step := range antigravitySteps(conversation) {
		if text := step.words(); text != "" {
			said = append(said, Turn{agyWords[step.kind].who, text})
		}
	}
	return said
}

// antigravityTyped is each user input of that conversation, dated by its step's metadata, field
// 1 a Timestamp; a step dated otherwise is nobody's answer (antigravity.py `user_messages`).  Never
// an error: the done check hands Antigravity's to Python (Reads).
func antigravityTyped(conversation string) (typed []Prompt, _ error) {
	var read agyReading
	for _, step := range antigravitySteps(conversation) {
		at, dated := read.timestamp(read.field(step.metadata, 1))
		if text := step.words(); step.kind == agyInput && dated && text != "" {
			typed = append(typed, Prompt{at, text})
		}
	}
	return typed, nil
}

// antigravitySteps is each user input and answer of that conversation, in order, read from its
// store as Python's harness.rows reads a harness's own: read-only, its write-ahead log included;
// none where there is none, or where it cannot be read.
func antigravitySteps(conversation string) (steps []agyStep) {
	path := antigravityStore(conversation)
	if path == "" {
		return nil
	}
	conn, err := sqlite.Open(path, sqlite3.OPEN_READONLY)
	if err != nil {
		return nil
	}
	defer conn.Close()
	conn.BusyTimeout(5 * time.Second) // sqlite3.connect's own
	stmt, _, err := conn.Prepare("SELECT step_type, metadata, step_payload FROM steps WHERE step_type IN (?, ?) ORDER BY idx")
	if err != nil {
		return nil
	}
	defer stmt.Close()
	if stmt.BindInt(1, agyInput) != nil || stmt.BindInt(2, agyAnswer) != nil {
		return nil
	}
	for stmt.Step() {
		row := make([]any, 3)
		if stmt.Columns(row...) != nil {
			return nil
		}
		kind, _ := row[0].(int64)
		metadata, _ := row[1].([]byte)
		payload, _ := row[2].([]byte)
		steps = append(steps, agyStep{kind, metadata, payload})
	}
	if stmt.Err() != nil {
		return nil
	}
	return steps
}

// words is what the step says, "" for none; agy writes them as protocol buffer strings, UTF-8
// throughout.
func (step agyStep) words() string {
	var read agyReading
	words := agyWords[step.kind]
	return strings.ToValidUTF8(string(read.field(read.field(step.payload, words.step), words.words)), "�")
}
