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

// looks is what an open screen knows of its own looks at every seat (menu.Live.met).
type looks struct {
	mu  sync.Mutex
	met map[string]bool // the seats its last look listed that every read since has listed
}

// watch has the screen read again within stir of news, the words as recorded (menu.Live._watch):
// a seat file, the runs' moved mark, usage.json or config.toml changed, or a project's switches
// landed.  With none for rereadEvery, every seat is looked at again.  read is one read, taking
// the home it read as it is given, and whether it landed.
func (l *looks) watch(read func(take func(seat.Home, time.Time) error) bool) {
	seen, last := marks(), time.Now()
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
		switch {
		case news && read(l.news):
		case time.Since(last) >= rereadEvery:
			read(l.look)
		default:
			continue
		}
		last = time.Now()
	}
}

// news takes a read on news: each live seat's word as recorded, captured and written by nobody,
// so no screen's read keeps waking another, or itself; but where it lists a seat no look of this
// screen's has met, a look at every seat (menu.Live.meet).
func (l *looks) news(home seat.Home, now time.Time) error {
	listed := names(home)
	l.mu.Lock()
	maps.DeleteFunc(l.met, func(name string, _ bool) bool { return !listed[name] }) // one that went and came back is new
	unmet := len(l.met) < len(listed)
	l.mu.Unlock()
	if unmet {
		return l.look(home, now)
	}
	return home.Recorded()
}

// look is a look at every seat, each one's word written down (Home.Announce), which meets them all.
func (l *looks) look(home seat.Home, now time.Time) error {
	if err := home.Announce(now); err != nil {
		return err
	}
	l.mu.Lock()
	l.met = names(home)
	l.mu.Unlock()
	return nil
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
