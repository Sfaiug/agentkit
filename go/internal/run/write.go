package run

import (
	"cmp"
	"context"
	"errors"
	"maps"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

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

// Writing is whether a write of the run's record, or of its delivery, is under way: its temporary
// file is there, a link left dangling among them (record.writing).
func Writing(dir string) bool {
	for _, name := range []string{"run.tmp", "delivery.tmp"} {
		if _, err := os.Lstat(filepath.Join(dir, name)); err == nil {
			return true
		}
	}
	return false
}

// Lined is whether the record holds a place in a landing line, or a wait in one to count: a
// write to it Python ak times, and adds to history.db as it ends, which Go has none of.
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

// RecoveryLock is the lock file a run's record is written under, which no commit of a checkout takes.
const RecoveryLock = "recovery.lock"

// holding is each directory whose recovery lock this process holds through Hold.
var holding sync.Map

// Hold waits for a run's or job's recovery lock and holds it until release, a Change of that
// run inside taking it as its own, as Python's recovery_lock is reentrant: the collector holds it
// across a checkout's removal, which records a checkout kept.
func Hold(dir string) (func(), error) {
	release, err := hold(dir, RecoveryLock)
	if err != nil {
		return nil, err
	}
	holding.Store(filepath.Clean(dir), true)
	return func() {
		holding.Delete(filepath.Clean(dir))
		release()
	}, nil
}

// Change is Python's `record`: change changes the record as it stands under recovery.lock,
// and what it changed is written, the old time budgets gone with the write as Python's
// record_limits drops them.  Nothing is written where change returns an error or changes
// nothing, nor with ErrLoneSurrogate or a record that cannot be read.
func Change(dir string, change func(*Object) error) error {
	return ChangeThen(dir, change, func() {})
}

// ChangeThen is Change with what then follows a write that landed, still under recovery.lock.
func ChangeThen(dir string, change func(*Object) error, then func()) error {
	if _, held := holding.Load(filepath.Clean(dir)); !held {
		release, err := hold(dir, RecoveryLock)
		if err != nil {
			return err
		}
		defer release()
	}
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
	if err := write(dir, data, before, record); err != nil {
		return err
	}
	then()
	return nil
}

// Deliver is Python's mark_delivery write: change changes the record as it stands, read and
// written under the run directory's lock alone, into delivery.tmp, nothing written where it returns
// an error.  Past recovery.lock on purpose: its caller holds delivery.lock, which Python's reap
// takes inside recovery.lock, so taking that one here would invert their order.
func Deliver(dir string, change func(*Object) error) error {
	return deliver(dir, hold, change)
}

// deliver is Deliver under the run directory's lock as take takes it.
func deliver(dir string, take func(dir, name string) (func(), error), change func(*Object) error) error {
	release, err := take(dir, "")
	if err != nil {
		return err
	}
	defer release()
	data, err := os.ReadFile(filepath.Join(dir, "run.json"))
	if err != nil {
		return errUnreadable
	}
	record, err := object(data)
	if record == nil {
		return cmp.Or(err, errUnreadable)
	}
	before := encoded(record)
	if err := change(record); err != nil || maps.Equal(before, encoded(record)) {
		return err
	}
	return lay(dir, data, before, record, "delivery.tmp")
}

// Create writes a run's first record as Change writes one, but without recovery.lock, as
// Python's first save: a stop refuses a run with no record, so none races it.
func Create(dir string, record *Object) error {
	return write(dir, []byte("{}"), map[string]string{}, record)
}

// write puts what changed from before, the record data held, to record onto the record as it
// stands under the run directory's lock.
func write(dir string, data []byte, before map[string]string, record *Object) error {
	if maps.Equal(before, encoded(record)) {
		return nil
	}
	release, err := hold(dir, "")
	if err != nil {
		return err
	}
	defer release()
	return lay(dir, data, before, record, "run.tmp")
}

// lay is a write of what changed under the run directory's lock its caller holds, through that
// temporary file.
func lay(dir string, data []byte, before map[string]string, record *Object, tmp string) error {
	path, after := filepath.Join(dir, "run.json"), encoded(record)
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
	// a place in the line counts from the write that gives it to the write that ends it, as
	// Python's _write_state counts it, its start read from the record as it stands
	if wait := current.Dict("waiting_on"); Member(current) && !wait.Has("fix") {
		if !current.Has("line_since") {
			current.Set("line_since", seconds(time.Now()))
		}
	} else {
		current.Delete("line_since")
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
	temp := filepath.Join(dir, tmp)
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
