// Package tick is ak's three-minute cron tick, as Python's agentkit/watch.py runs it. It hides
// the tick lock, which keeps one tick at a time, and the tick's log and its roll, which keep
// cron's `>>watch.log 2>&1` bounded. Go carries out only a tick that finds another holding the
// lock.
package tick

import (
	"context"
	"fmt"
	"io"
	"math/big"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/lock"
)

const (
	hung    = 30 * time.Minute // how long a tick may hold the lock before the log calls it hung
	logMax  = 5 << 20          // the log is rolled over to logKept once it passes this
	logName = "watch.log"      // the tick's own log; cron only redirects into it
	logKept = logName + ".1"   // one generation; there is nothing older to keep
)

// Overlap is a tick that finds another holding the lock: it makes ak's folders, as every tick
// does first, then says who holds the lock and for how long, and from 30 minutes calls it hung.
// False, with nothing written, while nobody holds the lock or ak's folders cannot be made, and
// on Windows, where no Python tick runs to hold it.
func Overlap(out, errOut io.Writer) bool {
	path := lockPath()
	if runtime.GOOS == "windows" || !lock.Held(path) || config.EnsureDirs() != nil {
		return false
	}
	pid, holding := holder(path)
	log := newLog(out, errOut)
	minutes := int(holding / time.Minute)
	log.line(fmt.Sprintf("tick already running (pid %s, for %d min)", pid, minutes))
	if holding >= hung {
		log.line(fmt.Sprintf("WARN the tick holding the lock has been running for %d min; "+
			"look at it, and kill it if it is hung", minutes))
	}
	return true
}

func lockPath() string { return filepath.Join(config.Home(), "state", "watch.tick.lock") }

func logPath() string { return filepath.Join(config.Home(), "tmp", logName) }

// holder is who holds the lock and for how long, off the file it wrote: its pid, as Python's
// int() reads the file's stripped text and 0 for what it cannot read, and its mtime, when that
// tick began.
func holder(path string) (*big.Int, time.Duration) {
	pid := new(big.Int)
	data, err := os.ReadFile(path)
	if number := config.Int(strings.TrimFunc(string(data), config.Space)); number != nil && err == nil && utf8.Valid(data) {
		pid = number
	}
	var holding time.Duration
	if info, err := os.Stat(path); err == nil {
		holding = max(0, time.Since(info.ModTime()))
	}
	return pid, holding
}

// log is the tick's printing, which keeps the log bounded where out or errOut is it.
type log struct {
	out     io.Writer
	streams []*os.File
	owned   map[*os.File]bool // found to be the log, kept because a roll unlinks the name under them
}

func newLog(out, errOut io.Writer) *log {
	l := &log{out: out, owned: map[*os.File]bool{}}
	for _, stream := range []io.Writer{out, errOut} {
		if file, ok := stream.(*os.File); ok {
			l.streams = append(l.streams, file)
		}
	}
	return l
}

// line prints one of the tick's lines, rolling the log it prints into first: the cron line only
// redirects, and the tick that never gets the lock is the only one writing while another hangs.
func (l *log) line(text string) {
	l.roll()
	fmt.Fprintln(l.out, text)
}

// roll moves the log past logMax over to logKept, under a lock and the size read again inside
// it, so two ticks that both saw it oversized do not both rename and lose the kept generation.
// Whoever rolled, the streams the log owns rejoin its live file.
func (l *log) roll() {
	path := logPath()
	kept := filepath.Join(config.Home(), "tmp", logKept)
	found := []os.FileInfo{}
	for _, name := range []string{path, kept} {
		if info, err := os.Stat(name); err == nil {
			found = append(found, info)
		}
	}
	// either name: a writer is at most one roll behind, since every line rejoins the live log
	for _, stream := range l.streams {
		if same(stream, found...) {
			l.owned[stream] = true
		}
	}
	if len(l.owned) == 0 {
		return
	}
	if info, err := os.Stat(path); err == nil && info.Size() > logMax {
		held, err := lock.Wait(context.Background(), filepath.Join(config.Home(), "state", logName+".lock"))
		if err == nil {
			if info, err := os.Stat(path); err == nil && info.Size() > logMax {
				os.Rename(path, kept)
			}
			held.Close()
		}
	}
	l.follow(path)
}

// follow puts the streams the log owns back on whatever its name points at now: a roll is a
// rename, and cron opened the file, not the name.
func (l *log) follow(path string) {
	live, err := os.Stat(path)
	var behind []*os.File
	for stream := range l.owned {
		if err != nil || !same(stream, live) {
			behind = append(behind, stream)
		}
	}
	if len(behind) == 0 {
		return
	}
	fresh, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
	if err != nil {
		return // a log we cannot reopen is no reason to lose the tick
	}
	defer fresh.Close()
	for _, stream := range behind {
		dup(fresh, stream)
	}
}

// same is whether stream's descriptor is the file any of found was stat'ed from.
func same(stream *os.File, found ...os.FileInfo) bool {
	ours, err := stream.Stat()
	if err != nil {
		return false
	}
	for _, info := range found {
		if os.SameFile(ours, info) {
			return true
		}
	}
	return false
}
