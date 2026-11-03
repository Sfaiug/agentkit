package tick

import (
	"errors"
	"io/fs"
	"os"

	"agentkit/internal/run"
)

// retireEvery is how often the switch lists are read, Python's retire.EVERY.
const retireEvery = 3600

// noSwitches is whether no checkout names a command for its feature switches: its AGENTS.md as
// written, which Python's retire.hand reads, and its default branch's.
func noSwitches() bool { return noneDeclares("features", true) }

// retire is the switch retirement row where no checkout names its switches (retire.hand): the
// hourly read of the lists, which reads none, stamped in its record.
func (t *ticking) retire() error {
	record, err := retireRecord()
	if err != nil {
		return err
	}
	now := epoch(t.clock())
	if asked, _ := record.Num("asked"); 0 <= now-asked && now-asked < retireEvery {
		return nil
	}
	record.Set("asked", now)
	return replaceFile(statePath("retire.json"), run.Encode(record)+"\n")
}

// retireRecord is retire.json as Python's retire.read reads it: a number for each key, and
// nothing for a record that is not one; a file it cannot read is an error.
func retireRecord() (*run.Object, error) {
	record := run.NewObject()
	data, err := os.ReadFile(statePath("retire.json"))
	if errors.Is(err, fs.ErrNotExist) {
		return record, nil
	}
	if err != nil {
		return nil, err
	}
	value, _ := run.DecodeLimited(data)
	read, ok := value.(*run.Object)
	if !ok {
		return record, nil
	}
	for _, key := range read.Keys() {
		at, ok := run.Num(read.Get(key))
		if !ok {
			return run.NewObject(), nil
		}
		record.Set(key, at)
	}
	return record, nil
}
