package harness

import (
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// An opencodeMessage is a user or assistant row of a session (opencode.py `_session_rows`): when
// OpenCode wrote it, in milliseconds, its data, and an answer's parts, text, reasoning and tool
// calls among them.
type opencodeMessage struct {
	user    bool
	created any
	data    *run.Object
	parts   []*run.Object
}

// opencodeMessages is each user and assistant row of that session in order, as opencode.py's
// `_session_rows` reads opencode.db, a row whose data is no JSON object holding nothing; none
// where there is no database.  The error where it is there and Python's sqlite3 cannot read it,
// which its `rows` raises reading strictly (harness.unread).
func opencodeMessages(session string) ([]opencodeMessage, error) {
	if !opencodeSession.MatchString(session) {
		return nil, nil
	}
	conn, known := opencodeOpen()
	if conn == nil && known {
		return nil, nil
	}
	unread := func(err error) error { return fmt.Errorf("cannot read %s: %w", opencodeDatabase(), err) }
	if conn == nil {
		return nil, unread(errors.New("not a database Go opens as Python's sqlite3 does"))
	}
	defer conn.Close()
	conn.BusyTimeout(5 * time.Second) // sqlite3.connect's own
	stmt, _, err := conn.Prepare("SELECT type, time_created, data FROM session_message WHERE session_id = ?" +
		" AND type IN ('user', 'assistant') ORDER BY seq")
	if err != nil {
		return nil, unread(err)
	}
	defer stmt.Close()
	if err := stmt.BindText(1, session); err != nil {
		return nil, unread(err)
	}
	var read []opencodeMessage
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
		// text or a blob, as json.loads reads either, a number decoding to no object; a lone
		// surrogate, as a tool output OpenCode cut mid-emoji holds, is U+FFFD, as Claude's are
		decoded, _ := run.DecodeShown(stmt.ColumnRawText(2))
		data, _ := decoded.(*run.Object)
		if data == nil {
			continue
		}
		message := opencodeMessage{user: row[0] == "user", created: row[1], data: data}
		if !message.user {
			for _, value := range data.List("content") {
				if part, ok := value.(*run.Object); ok {
					message.parts = append(message.parts, part)
				}
			}
		}
		read = append(read, message)
	}
	if err := stmt.Err(); err != nil {
		return nil, unread(err)
	}
	return read, nil
}

// opencodeAnswered reads the session the seat's record or receipt names, or the one a record of
// a session the seat left names (notify.Conversations), once for opencode.py's `said` and
// `answers`: each user row's `text` and each answer's text parts, and each question the owner
// answered on a card.  It is the done check's read: a receipt or database that is there and
// cannot be read is an error, never an owner who said nothing.
func opencodeAnswered(record map[string]any) (said []Turn, cards []Card, err error) {
	session, err := opencodeFound(record)
	if err != nil {
		return nil, nil, err
	}
	rows, err := opencodeMessages(session)
	if err != nil {
		return nil, nil, err
	}
	for _, row := range rows {
		if turn, shown := row.turn(); shown {
			said = append(said, turn)
		}
		for _, part := range row.parts {
			cards = append(cards, opencodeCards(part)...)
		}
	}
	return said, cards, nil
}

// opencodeCards is each question the owner answered on the card a part of an answer is: a
// `question` tool call OpenCode completed, which keeps their answers beside its questions, one
// list each, in the order asked -- the label picked, the words typed instead, or the labels
// ticked, joined as OpenCode's reply to the model joins them -- dated when they submitted the
// card.  A question whose answer is no list answers nothing; one of any other shape ends the card,
// as do choices of another shape.  An answer counts only where it is text and not blank, beside a
// question and choices all text.
func opencodeCards(part *run.Object) []Card {
	state, when := part.Dict("state"), part.Dict("time")
	if part.Get("type") != "tool" || part.Get("name") != "question" || state == nil || when == nil ||
		state.Get("status") != "completed" || state.Dict("input") == nil || state.Dict("metadata") == nil {
		return nil
	}
	at, dated := when.Num("completed")
	if !dated {
		return nil
	}
	questions, answers := state.Dict("input").List("questions"), state.Dict("metadata").List("answers")
	var found []Card
	for i := 0; i < min(len(questions), len(answers)); i++ {
		given, listed := answers[i].([]any)
		if !listed {
			continue
		}
		asked, _ := questions[i].(*run.Object)
		if asked == nil || !asked.Has("question") {
			return found
		}
		words := make([]string, len(given))
		for j, each := range given {
			word, isText := each.(string)
			if !isText {
				return found
			}
			words[j] = word
		}
		question, text := asked.Get("question").(string)
		var choices []Choice
		if asked.Truthy("options") {
			options, listed := asked.Get("options").([]any)
			if !listed {
				return found
			}
			for _, each := range options {
				option, _ := each.(*run.Object)
				if option == nil || !option.Has("label") {
					return found
				}
				label, labelled := option.Get("label").(string)
				description, described := "", true
				if option.Has("description") {
					description, described = option.Get("description").(string)
				}
				text = text && labelled && described
				choices = append(choices, Choice{label, description})
			}
		}
		if answer := strings.Join(words, ", "); text && strings.TrimFunc(answer, config.Space) != "" {
			found = append(found, Card{at / 1000, question, answer, choices})
		}
	}
	return found
}
