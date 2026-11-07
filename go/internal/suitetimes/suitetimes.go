// Package suitetimes is Python's suite_times record: each test's last measured seconds, per
// repository on this host, a file's or a part's as its file timed it (`<file>::<part>`), kept in
// ak's state as a suite's box throws its HOME writes away.  Every check keeps what it printed
// (Keep), and `ak run status --tests` lists it (Read).
package suitetimes

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// path is the record of the repository checkout checks out, Python's suite_times._path.
func path(checkout string) string {
	return filepath.Join(config.Home(), "state", "test-times-"+gitcall.RepositoryID(checkout)+".json")
}

// kept is that record as Python's suite_times.read takes it, each number of none or more by its
// test as written; none from anything but an object.  A lone surrogate, which Python reads and
// Go cannot write back, is run.ErrLoneSurrogate.
func kept(checkout string) (*run.Object, error) {
	times := run.NewObject()
	data, _ := os.ReadFile(path(checkout))
	value, err := run.DecodeLimited(data)
	if errors.Is(err, run.ErrLoneSurrogate) {
		return times, err
	}
	if record, ok := value.(*run.Object); ok {
		for _, test := range record.Keys() {
			if seconds, ok := run.Num(record.Get(test)); ok && seconds >= 0 {
				times.Set(test, record.Get(test))
			}
		}
	}
	return times, nil
}

// Read is the seconds each test of checkout's repository took when it last passed, by test.
func Read(checkout string) map[string]float64 {
	record, _ := kept(checkout)
	times := map[string]float64{}
	for _, test := range record.Keys() {
		times[test], _ = run.Num(record.Get(test))
	}
	return times
}

// Keep adds found, the seconds a check printed by test, to the record of checkout, the checkout it
// ran on, under ak's state lock, as Python's suite_times.keep: a test's latest time wins, and a
// test whose file that checkout no longer has leaves the record, a part with its file.  A record
// it cannot write stays as it was: the next suite's pieces are cut by size until a later one keeps
// its times.
func Keep(checkout string, found map[string]float64) {
	if len(found) == 0 || config.EnsureDirs() != nil {
		return
	}
	held, err := lock.Wait(context.Background(), filepath.Join(config.Home(), "state", "watch.lock"))
	if err != nil {
		return
	}
	defer held.Close()
	times, err := kept(checkout)
	if err != nil {
		return
	}
	for test, seconds := range found {
		times.Set(test, run.Float(seconds))
	}
	tests := times.Keys()
	sort.Strings(tests)
	record := run.NewObject()
	for _, test := range tests {
		if has(checkout, test) {
			record.Set(test, times.Get(test))
		}
	}
	file := path(checkout)
	saved, err := os.CreateTemp(filepath.Dir(file), "tmp")
	if err != nil {
		return
	}
	if _, err = saved.WriteString(run.Line(record)); saved.Close() != nil || err != nil || os.Rename(saved.Name(), file) != nil {
		os.Remove(saved.Name())
	}
}

// has is whether checkout has the file a test is, or is a part of, as a file.
func has(checkout, test string) bool {
	file, _, _ := strings.Cut(test, "::")
	if !filepath.IsAbs(file) {
		file = filepath.Join(checkout, file)
	}
	info, err := os.Stat(file)
	return err == nil && info.Mode().IsRegular()
}
