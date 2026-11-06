package run

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// The owner's call on 2 Nov 2026, to bring an idle screen near 0.05 cores: the screen reads again
// only the runs that can change, and a row may show a run at rest stale until the next full read.
// Python's open_runs names these WRITTEN, SHARE and CEILING.
const (
	// how long a record's write keeps its run open: a home writing more ended runs looks at more on
	// every read, one writing fewer at fewer
	writtenOpen = time.Hour
	// the part of a core looking at every run spends at most: more runs or a slower disk space full
	// reads out up to ceiling, and few runs or a faster one bring them together until every read is
	// a full one.  Measured on the clock, which no call of Go's own splits from other goroutines'
	// CPU: a read waiting on anything spaces the next out further
	share = 0.005
	// how late a run at rest is at most: a full read costing less comes sooner (share), and one
	// costing more than ceiling * share spends more CPU rather than show a staler row.  Not derived
	// from the machine: it bounds how stale a row may be, which the machine's speed does not change
	ceiling = 60 * time.Second
	// since a file's last write in which its stat vouches for no parse: a filesystem's clock can
	// give two writes in one tick the same times (Python's parsed.FRESH)
	fresh = time.Second
)

// A Held is a run with a readable record as a Reader last looked at it: its directory's name, its
// record and when that was written, and whether it is the smoke suite's (SmokeRun).
type Held struct {
	Name    string
	Record  *Object
	Written time.Time
	Smoke   bool
}

// A Reader is what one process knows of the runs between its reads, so that a run long over costs
// an open screen next to nothing (Python's open_runs.Reader).  A run is open when it has no
// readable record, its state has not ended, or its record was written within the hour or too
// freshly to vouch for; otherwise it is at rest.  A read looks at the open runs, a record parsed
// and its paths resolved only once its stat changed, and at runs/ listed again only once it
// changed.  A full read looks at every run again, its paths resolved and its openness decided
// again, so a run at rest that moved, or a symlink that did, shows by then.  A new Reader's first
// read is a full one.
type Reader struct {
	mu      sync.Mutex
	listing os.FileInfo     // runs/ as it was listed, nil while that vouches for nothing
	names   []string        // the run directories, in name order
	held    map[string]kept // each looked at, by name
	open    map[string]bool // those a read looks at
	due     time.Time       // when the next full read is
}

type kept struct {
	Held
	info os.FileInfo // run.json as it was parsed, nil while that vouches for nothing
	bad  bool        // run.json is there and holds no record Go reads
}

// Read is each run with a readable record, in name order, and false where runs/ or a run.json
// cannot be read.  Records are every reader's: only read them.
func (reader *Reader) Read() ([]Held, bool) {
	reader.mu.Lock()
	defer reader.mu.Unlock()
	began := time.Now()
	full := !began.Before(reader.due)
	if !reader.list(began) {
		return nil, false
	}
	smoke := Smoke()
	for _, name := range reader.names {
		if full || reader.open[name] {
			reader.look(name, full, smoke, began)
		}
	}
	if full {
		reader.due = time.Now().Add(min(ceiling, time.Duration(float64(time.Since(began))/share)))
	}
	var found []Held
	for _, name := range reader.names {
		each, ok := reader.held[name]
		if ok && each.bad {
			return nil, false
		} else if ok {
			found = append(found, each.Held)
		}
	}
	return found, true
}

// list reads runs/ again once its stat changed, each directory new to it open and each gone
// forgotten.
func (reader *Reader) list(now time.Time) bool {
	info, err := os.Stat(Runs())
	if err == nil && reader.listing != nil && same(reader.listing, info) {
		return true
	}
	entries, err := os.ReadDir(Runs())
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return false
	}
	before, listed := reader.held, map[string]bool{}
	reader.names, reader.held, reader.open, reader.listing = nil, map[string]kept{}, map[string]bool{}, vouching(info, now)
	for _, entry := range entries {
		dir := entry.IsDir()
		if entry.Type()&fs.ModeSymlink != 0 {
			found, err := os.Stat(filepath.Join(Runs(), entry.Name()))
			dir = err == nil && found.IsDir()
		}
		if dir {
			reader.names, listed[entry.Name()] = append(reader.names, entry.Name()), true
		}
	}
	for name := range listed {
		if each, ok := before[name]; ok {
			reader.held[name], reader.open[name] = each, each.opens(now)
		} else {
			reader.open[name] = true
		}
	}
	return true
}

// look is one run as its run.json now stands: parsed again and its paths resolved once its stat
// changed, and on a full read its paths resolved again.
func (reader *Reader) look(name string, full bool, smoke func(*Object) bool, now time.Time) {
	path := filepath.Join(Runs(), name, "run.json")
	each := reader.held[name]
	info, err := os.Stat(path)
	if each.info == nil || err != nil || !same(each.info, info) {
		var record *Object
		if err == nil {
			record, err = ReadJSON(path)
		}
		each = kept{Held: Held{Name: name, Record: record}, bad: err != nil && !errors.Is(err, fs.ErrNotExist) || err == nil && record == nil}
		if record != nil {
			each.Written, each.Smoke = info.ModTime(), smoke(record)
		}
	} else if full && each.Record != nil {
		each.Smoke = smoke(each.Record)
	}
	if each.info = vouching(info, now); each.Record == nil && !each.bad {
		delete(reader.held, name)
	} else {
		reader.held[name] = each
	}
	reader.open[name] = each.opens(now)
}

// opens is whether a read looks at that run: it has no readable record, its state has not ended, or
// it was written within the hour or too freshly to vouch for.
func (each kept) opens(now time.Time) bool {
	return each.Record == nil || each.bad || each.info == nil || !Ended(each.Record) || now.Sub(each.Written) < writtenOpen
}

// vouching is that stat where what was read under it holds while the stat does, else nil: by the
// file's mtime, where Python's parsed reads its ctime, which Go's standard library reads alike on
// no two systems.
func vouching(info os.FileInfo, now time.Time) os.FileInfo {
	if info == nil || now.Sub(info.ModTime()) < fresh {
		return nil
	}
	return info
}

// same is whether a file's stat reads as it did: the same file, written last at the same time,
// the same size.  Every write ak makes replaces the file.
func same(was, now os.FileInfo) bool {
	return os.SameFile(was, now) && was.ModTime().Equal(now.ModTime()) && was.Size() == now.Size()
}
