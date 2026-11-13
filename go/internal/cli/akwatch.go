package cli

import (
	"maps"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/features"
	"agentkit/internal/parsed"
	"agentkit/internal/seat"
)

// stir is how often the ak screen looks for news (menu.STIR).
const stir = time.Second

// looks is an open screen's reads on news and its looks at every seat behind them (menu.Live).
type looks struct {
	read    func(take func(seat.Home, time.Time) error) bool // one read, taking the home it read, and whether it landed
	mu      sync.Mutex
	met     map[string]bool // the seats a look of this screen's has listed, that every read since has listed
	passing bool            // a look is going
	again   bool            // and another was asked for meanwhile
	landed  time.Time       // when a read last landed, or the clock last asked for a look
}

// watch reads again within stir of news, the words as recorded (menu.Live._watch): a seat file,
// the runs' moved mark, usage.json or config.toml changed, or a project's switches landed.  With
// no read landing for rereadEvery, every seat is looked at again.
func (l *looks) watch() {
	seen := marks()
	l.landing(nil) // the clock starts with the screen
	for {
		news := false
		select {
		case <-time.After(stir):
		case <-features.Landed():
			news = true
		}
		now := marks() // noted before the read: what is written while it reads is news to the next
		news = news || !slices.EqualFunc(now, seen, parsed.Same)
		seen = now
		if !(news && l.read(l.news)) && l.quiet() {
			l.look()
		}
	}
}

// quiet is whether no read has landed for rereadEvery, the clock started again where none has.
func (l *looks) quiet() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if time.Since(l.landed) < rereadEvery {
		return false
	}
	l.landed = time.Now()
	return true
}

// landing is a take's answer, the clock started again where it lets its read land.
func (l *looks) landing(err error) error {
	if err == nil {
		l.mu.Lock()
		l.landed = time.Now()
		l.mu.Unlock()
	}
	return err
}

// news takes a read on news: the words as recorded, captured and written by nobody, so no
// screen's read keeps waking another, or itself; where it lists a seat no look of this screen's
// has met, a look starts behind it, which it does not wait on (menu.Live.meet).
func (l *looks) news(home seat.Home, now time.Time) error {
	listed := names(home)
	l.mu.Lock()
	maps.DeleteFunc(l.met, func(name string, _ bool) bool { return !listed[name] }) // one that went and came back is new
	unmet := len(l.met) < len(listed)
	if unmet {
		l.met = listed
	}
	l.mu.Unlock()
	if unmet {
		l.look()
	}
	return l.landing(home.Recorded(now))
}

// look has every seat looked at in a pass of its own, one at a time: one asked for while another
// goes follows it.
func (l *looks) look() {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.passing {
		l.again = true
		return
	}
	l.passing = true
	go func() {
		for again := true; again; {
			l.read(l.meet)
			l.mu.Lock()
			again, l.again = l.again, false
			l.passing = again
			l.mu.Unlock()
		}
	}()
}

// meet is a pass's take: every seat looked at, each one's word written down (Home.Announce), and
// all it listed met.
func (l *looks) meet(home seat.Home, now time.Time) error {
	listed := names(home)
	l.mu.Lock()
	l.met = listed
	l.mu.Unlock()
	return l.landing(home.Announce(now))
}

func names(home seat.Home) map[string]bool {
	listed := map[string]bool{}
	for _, each := range home.Seats {
		listed[each.Name] = true
	}
	return listed
}

// marks is the stat of each file whose change is news (menu.Live.recorded, config_mark), as
// parsed.Same compares them: every write replaces the file.
func marks() []os.FileInfo {
	state := filepath.Join(config.Home(), "state")
	paths := append([]string{filepath.Join(config.Home(), "config.toml"), filepath.Join(state, "usage.json"),
		filepath.Join(state, "runs-moved")}, config.SeatRecords("seat")...)
	var found []os.FileInfo
	for _, path := range paths {
		if info, err := os.Stat(path); err == nil {
			found = append(found, info)
		}
	}
	return found
}
