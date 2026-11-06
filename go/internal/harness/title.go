package harness

import (
	"bufio"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Titles is whether that harness's seat takes a title line (its plugin's `title_command`).
func Titles(name string) bool { return plugins[name].titled }

// SessionTitle is the custom title the conversation a seat's record names was last given (its
// plugin's `session_title`): "" for none, nil where it cannot be read or its harness keeps none Go
// reads.  Kept is what cache, the reading carried over from the last, is to hold now, nil where it
// holds that already: a reading only reads what the conversation added since.
func SessionTitle(name string, record *run.Object, cache string) (title any, kept *run.Object) {
	if hook := plugins[name].title; hook != nil {
		return hook(record, cache)
	}
	return nil, nil
}

// claudeTitle is claude.py's `session_title`: the last `custom-title` line naming the conversation.
func claudeTitle(record *run.Object, cache string) (any, *run.Object) {
	conversation, cwd := record.Str("conversation"), record.Str("cwd")
	if conversation == "" || cwd == "" {
		return nil, nil
	}
	path := claudeConversation(map[string]any{"conversation": conversation, "cwd": cwd, "account": record.Get("account")})
	info, err := os.Stat(path)
	if err != nil {
		return nil, nil
	}
	stamp, stamped := fileStamp(info)
	if !stamped {
		return nil, nil
	}
	var title any
	offset, readable := int64(0), true
	cached, _ := run.ReadJSON(cache)
	if cached == nil {
		cached = run.NewObject()
	}
	if wasReadable, ok := cached.Get("readable").(bool); ok && cached.Get("path") == path {
		before, _ := cached.Get("stamp").([]any)
		stop, whole := wholeNumber(cached.Get("offset"))
		var size int64
		sized := len(before) == len(stamp)
		if sized {
			size, sized = wholeNumber(before[2])
		}
		if sized && whole && 0 <= stop && stop <= size {
			switch {
			case run.Equal(before, stamp):
				if !wasReadable {
					return nil, nil
				}
				return titled(cached.Get("title")), nil
			case run.Equal(before[:2], stamp[:2]) && size < info.Size():
				title, offset, readable = cached.Get("title"), stop, wasReadable
			}
		}
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, nil
	}
	defer file.Close()
	if _, err := file.Seek(offset, io.SeekStart); err != nil {
		return nil, nil
	}
	reader := bufio.NewReader(io.LimitReader(file, info.Size()-offset))
	for offset < info.Size() {
		line, err := reader.ReadBytes('\n')
		if err != nil && err != io.EOF {
			return nil, nil
		}
		if len(line) == 0 || line[len(line)-1] != '\n' {
			// a line still being written may end inside a character, never on a broken one
			readable = readable && startsWhole(line)
			break
		}
		offset += int64(len(line))
		if !utf8.Valid(line) {
			readable = false
			break
		}
		if !strings.Contains(string(line), `"custom-title"`) {
			continue
		}
		value, _ := run.Decode(line)
		if event, ok := value.(*run.Object); ok && event.Get("type") == "custom-title" && event.Get("sessionId") == conversation {
			title = event.Get("customTitle")
		}
	}
	if title = titled(title); !readable {
		title = nil
	}
	return title, run.Fields("path", path, "stamp", stamp, "offset", run.Number(strconv.FormatInt(offset, 10)),
		"title", title, "readable", readable)
}

// titled is a title as a reading gives it: "" for one that is no text or only spaces.
func titled(value any) any {
	if text, ok := value.(string); ok && strings.TrimFunc(text, config.Space) != "" {
		return text
	}
	return ""
}

// startsWhole is whether bytes are UTF-8 as far as they go: whole characters, the last perhaps cut.
func startsWhole(data []byte) bool {
	for len(data) > 0 {
		r, size := utf8.DecodeRune(data)
		if r == utf8.RuneError && size <= 1 {
			return len(data) < utf8.UTFMax && !utf8.FullRune(data)
		}
		data = data[size:]
	}
	return true
}

// wholeNumber is a JSON number Python reads as an int.
func wholeNumber(value any) (int64, bool) {
	number, ok := value.(run.Number)
	if !ok {
		return 0, false
	}
	parsed, err := strconv.ParseInt(string(number), 10, 64)
	return parsed, err == nil
}

// KeepTitle writes what a title reading's cache is to hold, as claude.py's `_write` replaces a file:
// whole, through a temporary beside it, the mode it had kept.
func KeepTitle(cache string, kept *run.Object) error {
	tmp, err := os.CreateTemp(filepath.Dir(cache), filepath.Base(cache)+".*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	_, err = tmp.WriteString(run.Line(kept) + "\n")
	if closed := tmp.Close(); err == nil {
		err = closed
	}
	if info, statErr := os.Stat(cache); err == nil && statErr == nil {
		err = os.Chmod(tmp.Name(), info.Mode().Perm())
	}
	if err != nil {
		return err
	}
	return os.Rename(tmp.Name(), cache)
}
