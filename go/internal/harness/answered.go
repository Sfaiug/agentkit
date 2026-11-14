package harness

import (
	"bufio"
	"errors"
	"io"
	"io/fs"

	"agentkit/internal/run"
)

// A Card is a question the owner answered on the seat's own question card: when, the question
// and choices in the seat's words, and the answer in the owner's (Python's plugin `answers`).
type Card struct {
	At               float64
	Question, Answer string
	Choices          []Choice
}

// A Choice is one a question card offered.
type Choice struct{ Label, Description string }

// Reads is whether Go reads the owner's words in that harness's conversations, their messages and
// their answers on its question cards (Answered), and, strictly, as strictly as Python's done
// check does (harness.strictly): a harness that brings no Python reads none, as its default hooks.
func Reads(name string, strictly bool) bool {
	own, plugged := plugins[name]
	if own.answered == nil {
		return !plugged && seatDefaults(name).seats
	}
	return !strictly || !own.loose
}

// Answered is the conversation that seat's record owns as its harness shows it, oldest first
// (Said), and each answer its owner gave on its question cards, of a harness Go reads (Reads): an
// error where the conversation is there and cannot be read.
func Answered(name string, record map[string]any) ([]Turn, []Card, error) {
	if hook := plugins[name].answered; hook != nil {
		return hook(record)
	}
	return nil, nil, nil
}

// Replies is whether that message of the owner's, in a conversation of that harness, is their
// reply on a question card, which counts only as the answers it gave (Answered): its words repeat
// the seat's question (Python's `user_messages` `replies`).
func Replies(name, text string) bool {
	hook := plugins[name].replies
	return hook != nil && hook(text)
}

// Entries calls each with every JSON object the file at path holds a line, first line first, as
// Python's harness.entries reads a growing record: an unfinished last line can wait, and no
// path or no file holds none.  What cannot be read is an error.
func Entries(path string, each func(*run.Object)) error {
	if path == "" {
		return nil
	}
	return EntriesBy([]string{path}, each)
}

// EntriesBy is Entries of a record read by those names, by the first of them there as it is opened
// (Open).
func EntriesBy(names []string, each func(*run.Object)) error {
	file, err := Open(names...)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer file.Close()
	for reader := bufio.NewReader(file); ; {
		line, err := reader.ReadBytes('\n')
		value, _ := run.DecodeShown(line)
		if entry, ok := value.(*run.Object); ok {
			each(entry)
		}
		if err == io.EOF {
			return nil
		} else if err != nil {
			return err
		}
	}
}
