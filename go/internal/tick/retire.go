package tick

import (
	"errors"
	"io/fs"
	"os"

	"agentkit/internal/features"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

const (
	retireEvery = 3600  // how often the switch lists are read, Python's retire.EVERY
	retireAgain = 86400 // a checkout whose lines were written is read again this long after
)

// retire is the switch retirement row (retire.hand): once every retireEvery, each checkout not
// written for retireAgain whose AGENTS.md names a features command gets an open line, in a seat
// filed under it, for each switch its list shows proven or on for everyone with no everyone_since.
// Every list, plan and word is read before a line is written, so one Go does not read as Python
// does leaves the row to Python with nothing done.
func (t *ticking) retire() error {
	record, err := retireRecord()
	if err != nil {
		return err
	}
	now := t.clock()
	if asked, _ := record.Num("asked"); 0 <= epoch(now)-asked && epoch(now)-asked < retireEvery {
		return nil
	}
	checkouts, _ := seat.Checkouts()
	var hands []handing
	for _, checkout := range checkouts {
		if at, _ := record.Num(checkout); 0 <= epoch(now)-at && epoch(now)-at < retireAgain || !features.Named(checkout) {
			continue
		}
		hand, err := handed(checkout, now)
		if err != nil {
			return err
		}
		hands = append(hands, hand)
	}
	record.Set("asked", epoch(now))
	for _, hand := range hands {
		if t.hand(hand) {
			record.Set(hand.checkout, epoch(now))
		}
	}
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
