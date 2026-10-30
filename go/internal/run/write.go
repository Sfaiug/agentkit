package run

import (
	"cmp"
	"context"
	"errors"
	"maps"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/lock"
)

// A write hides two things from its callers.  The locks, each taken when Python ak takes it:
// recovery.lock's, which every save and a stop hold, from the read to the write, and the run
// directory's own, which every write holds, around the write alone (`hold`), so the two
// programs never interleave on one record.  And the layout: what changed goes onto the record
// as it stands under the second lock, each member left as it was kept in the JSON text it was
// read in, the others replaced, dropped or appended, laid out as Python's
// json.dumps(record, indent=2) lays it out, into run.tmp and renamed over run.json, so it
// lands whole or not at all.

// ErrLined is a write Python ak does more for than write the file (`Lined`).
var ErrLined = errors.New("a record with a place in a line")

// Lined is whether the record holds a place in a landing line, or a wait in one to count: a
// write to it Python ak times or adds to history.db.
func Lined(record *Object) bool {
	return InLine(record) || record.Has("line_since")
}

var errUnreadable = errors.New("run.json cannot be read")

// hold waits for one of Python ak's locks on a run, held until release: the named file's in
// the run's directory, or with no name the directory's own.
func hold(dir, name string) (func(), error) {
	file, err := lock.Wait(context.Background(), filepath.Join(dir, name))
	if err != nil {
		return nil, err
	}
	return func() { file.Close() }, nil
}

// Change is Python's `record`: change changes the record as it stands under recovery.lock,
// and what it changed is written, the old time budgets gone with the write as Python's
// record_limits drops them.  Nothing is written where change returns an error or changes
// nothing, nor with ErrLoneSurrogate, ErrLined or a record that cannot be read.
func Change(dir string, change func(*Object) error) error {
	release, err := hold(dir, "recovery.lock")
	if err != nil {
		return err
	}
	defer release()
	path := filepath.Join(dir, "run.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return errUnreadable
	}
	record, err := object(data)
	if record == nil {
		return cmp.Or(err, errUnreadable)
	}
	before := encoded(record)
	if err := change(record); err != nil {
		return err
	}
	after := encoded(record)
	if maps.Equal(before, after) {
		return nil
	}
	release, err = hold(dir, "")
	if err != nil {
		return err
	}
	defer release()
	if again, err := os.ReadFile(path); err == nil {
		if current, err := object(again); errors.Is(err, ErrLoneSurrogate) {
			return err
		} else if current != nil {
			data = again
		}
	}
	current, _ := object(data)
	read := encoded(current)
	for key := range before {
		if _, kept := after[key]; !kept {
			current.Delete(key)
		}
	}
	for _, key := range record.keys {
		if before[key] != after[key] {
			current.Set(key, record.Get(key))
		}
	}
	if Lined(current) {
		return ErrLined
	}
	for _, key := range []string{"done_when_minutes", "turn_hours", "stall_minutes"} {
		current.Delete(key)
	}
	if !current.Has("silence_minutes") {
		current.Set("silence_minutes", SilenceMinutes)
	}
	if !current.Has("ceiling_hours") {
		current.Set("ceiling_hours", CeilingHours)
	}
	texts := members(data)
	lines := make([]string, len(current.keys))
	for i, key := range current.keys {
		text, kept := texts[key]
		value := Encode(current.Get(key))
		if kept && read[key] == value {
			value = text[1]
		} else {
			text[0] = quote(key)
		}
		lines[i] = "  " + text[0] + ": " + laidOut(value, "  ")
	}
	temp := filepath.Join(dir, "run.tmp")
	if err := os.WriteFile(temp, []byte("{\n"+strings.Join(lines, ",\n")+"\n}"), 0666); err != nil {
		return err
	}
	return os.Rename(temp, path)
}

// encoded is each member's JSON text, by key.
func encoded(record *Object) map[string]string {
	texts := map[string]string{}
	for _, key := range record.keys {
		texts[key] = Encode(record.Get(key))
	}
	return texts
}

// members is each top-level member's key and value as the JSON text of an object Decode read:
// a repeated key's first text and its last value, as Python keeps them.
func members(data []byte) map[string][2]string {
	found := map[string][2]string{}
	p := &parser{data: data}
	p.space()
	p.take("{")
	for p.space(); !p.take("}"); p.space() {
		p.take(",")
		p.space()
		start := p.at
		key, _ := p.text()
		text, kept := found[key]
		if !kept {
			text[0] = string(data[start:p.at])
		}
		p.space()
		p.take(":")
		p.space()
		start = p.at
		p.value(1)
		text[1] = string(data[start:p.at])
		found[key] = text
	}
	return found
}

// laidOut is JSON text with its whitespace as json.dumps(indent=2) puts it, `indent` deep, and
// every string, number and word as written.
func laidOut(text, indent string) string {
	var out strings.Builder
	for i := 0; i < len(text); i++ {
		switch c := text[i]; c {
		case ' ', '\t', '\n', '\r':
		case '"':
			end := i + 1
			for ; text[end] != '"'; end++ {
				if text[end] == '\\' {
					end++
				}
			}
			out.WriteString(text[i : end+1])
			i = end
		case '{', '[':
			out.WriteByte(c)
			if next := strings.TrimLeft(text[i+1:], " \t\n\r"); next[0] == '}' || next[0] == ']' {
				continue
			}
			indent += "  "
			out.WriteString("\n" + indent)
		case '}', ']':
			if previous := strings.TrimRight(text[:i], " \t\n\r"); !strings.HasSuffix(previous, "{") && !strings.HasSuffix(previous, "[") {
				indent = indent[2:]
				out.WriteString("\n" + indent)
			}
			out.WriteByte(c)
		case ',':
			out.WriteString(",\n" + indent)
		case ':':
			out.WriteString(": ")
		default:
			out.WriteByte(c)
		}
	}
	return out.String()
}
