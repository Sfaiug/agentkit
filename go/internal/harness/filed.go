package harness

import (
	"errors"
	"io/fs"
	"os"
)

// FiledIn is the conversation a seat's record names and the names of the one file its owner's
// words are read from, in order, none where it has no file yet (Python's Harness.read_by): false
// where its harness keeps it in no file of its own Go names, so whatever reads it reads it whole.
func FiledIn(name string, record map[string]any) (conversation string, names []string, filed bool) {
	hook := plugins[name].readBy
	if hook == nil {
		return "", nil, false
	}
	conversation, _ = record["conversation"].(string)
	return conversation, hook(record), true
}

// Stamp is what Python's os.stat says of the file at path, [st_dev, st_ino, st_size,
// st_mtime_ns], following a link as it does; nil where it is not there, the error where it is
// and cannot be read so, and false where Go reads no such stamp here (fileStamp).
func Stamp(path string) ([]any, bool, error) {
	info, err := os.Stat(path)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return nil, true, nil
	case err != nil:
		return nil, false, err
	}
	stamp, stamped := fileStamp(info)
	if !stamped {
		return nil, false, nil
	}
	return stamp[:4], true, nil
}
