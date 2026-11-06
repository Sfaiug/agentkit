package harness

import (
	"bufio"
	"errors"
	"io"
	"io/fs"
	"os"

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

// Answered is the conversation that seat's record owns as its harness shows it, oldest first
// (Said), and each answer its owner gave on its question cards: an error where the conversation
// is there and cannot be read; false where Go reads neither for that harness yet.
func Answered(name string, record map[string]any) ([]Turn, []Card, bool, error) {
	hook := plugins[name].answered
	if hook == nil {
		return nil, nil, false, nil
	}
	said, cards, err := hook(record)
	return said, cards, true, err
}

// entries calls each with every JSON object the file at path holds a line, first line first, as
// Python's harness.entries reads a growing record: an unfinished last line can wait, and no
// path or no file holds none.  What cannot be read is an error.
func entries(path string, each func(*run.Object)) error {
	if path == "" {
		return nil
	}
	file, err := os.Open(path)
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
