package harness

import (
	"errors"
	"io/fs"
	"os"
)

// ReadBy is the names the conversation a seat's record names is read by, in order (Python's plugin
// `read_by`): the file its harness keeps it in (Conversation), then any name ak gave that file
// which outlives it there; none where the record names none, false where Go does not read that
// harness's conversations yet.
func ReadBy(name string, record map[string]any) ([]string, bool) {
	if hook := plugins[name].readBy; hook != nil {
		return hook(record), true
	}
	path, known := Conversation(name, record)
	if path == "" {
		return nil, known
	}
	return []string{path}, known
}

// Open is the record read by those names open to read, by the first of them there as it is opened
// (harness._opened), so a name gone even as it is read is read by the next; fs.ErrNotExist where
// none is.
func Open(names ...string) (*os.File, error) {
	err := fs.ErrNotExist
	for _, name := range names {
		var file *os.File
		if file, err = os.Open(name); !errors.Is(err, fs.ErrNotExist) {
			return file, err
		}
	}
	return nil, err
}
