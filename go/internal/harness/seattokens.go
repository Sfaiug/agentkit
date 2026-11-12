package harness

import (
	"bufio"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/run"
)

// A Spend is what one line of a seat's usage file counts, as its harness reads it (Python's
// plugin `seat_token_usage`): where the line starts in its file, when in Unix seconds, the event
// it is ("" where its line is), its tokens, its model (nil where the harness does not say), and
// its input, cache write, cache read and output (nil where it does not say).
type Spend struct {
	Start  int64
	At     float64
	Event  string
	Tokens int
	Model  any
	Counts []int
}

// TokenSources is the files that harness keeps what the record's seat and its children spend in,
// Python's plugin `seat_token_sources`: false where no reader counts its seats, Python's None.
func TokenSources(name string, record *run.Object) ([]string, bool) {
	if hook := plugins[name].tokenSources; hook != nil {
		return hook(record), true
	}
	return nil, false
}

// Spends is what the whole lines that harness's file at path holds past cursor count, as Python's
// seat_tokens reads them, the cursor moved past them: the file read from its start where another
// is at its path or it shrank, and a line with no newline yet left for the next reading.  The
// cursor also keeps what the harness carries from line to line.  An error where the file cannot
// be read; false where Go cannot tell one file from another as Python does here.
func Spends(name, path string, cursor *run.Object) ([]Spend, bool, error) {
	cursor.Set("source", path)
	file, err := os.Open(path)
	if err != nil {
		return nil, true, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err == nil && info.IsDir() {
		err = &fs.PathError{Op: "open", Path: path, Err: errors.New("is a directory")}
	}
	if err != nil {
		return nil, true, err
	}
	stamp, told := fileStamp(info)
	if !told {
		return nil, false, nil
	}
	identity := stamp[:2]
	at, _ := cursor.Int("offset")
	offset := int64(at)
	if !run.Equal(cursor.Get("identity"), identity) || offset > info.Size() {
		offset = 0
	}
	if _, err := file.Seek(offset, io.SeekStart); err != nil {
		return nil, true, err
	}
	var spent []Spend
	lines := bufio.NewReader(io.LimitReader(file, info.Size()-offset))
	for {
		line, err := lines.ReadBytes('\n')
		if errors.Is(err, io.EOF) {
			break // the harness may still be writing this line
		}
		if err != nil {
			return nil, true, err
		}
		start := offset
		offset += int64(len(line))
		value, _ := run.DecodeShown(line)
		entry, _ := value.(*run.Object)
		hook := plugins[name].tokenUsage
		if entry == nil || hook == nil {
			continue
		}
		if spend, counts := hook(entry, cursor); counts && spend.At != 0 {
			spend.Start = start
			spent = append(spent, spend)
		}
	}
	cursor.Set("identity", identity)
	cursor.Set("offset", int(offset))
	return spent, true, nil
}

// below is every file under root, at any depth, whose name matches the pattern, as Python's
// Path.rglob finds them: root followed where it is a link, no link to a folder under it.
func below(root, pattern string) []string {
	var found []string
	walked := root + string(filepath.Separator)
	filepath.WalkDir(walked, func(path string, entry fs.DirEntry, err error) error {
		if err == nil && path != walked {
			if matched, _ := filepath.Match(pattern, entry.Name()); matched {
				found = append(found, path)
			}
		}
		return nil
	})
	return found
}
