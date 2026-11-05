package seat

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// stale is how long a record whose seat is gone is kept (config.SESSION_STALE).
const stale = 7 * 86400

// Past is whether the owner stopped it: it has no row, only the past screen's number.
func (seat Seat) Past() bool { return seat.closed && !seat.held }

// Checkout is the project it is filed under, "" for none.
func (seat Seat) Checkout() string {
	if len(seat.home) == 3 {
		return seat.home[2]
	}
	return ""
}

// Unsent is what nobody sent, left in its composer.
func (seat Seat) Unsent() string { return seat.unsent }

// ModelName is the model it runs at the effort it orchestrates at (config.ModelAt), and alone.
func (home Home) ModelName(seat Seat) (at, alone string) {
	models := home.models
	if record, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "session-"+seat.Name+".json")); record != nil {
		models = atEfforts(models, record)
	}
	return config.ModelAt(seat.Orchestrator, "effort", models), config.ModelName(seat.Orchestrator, models)
}

// Settled is whether the ak screen's first frame would leave this home as it is: what menu.main does
// first would change nothing but the two things that decide nothing.  With no boot_id,
// resume_after_boot only writes a baseline; and the tick stamps the seats' retention clocks as the
// menu does. Runs are read without maintenance by Menu. A record a week
// old it retires; a stranger on ak's server it may save and close; another boot's mark it resumes
// after.  A project naming its feature
// switches has Python run its command, and a job draws a line Go has no port of.
func (home Home) Settled(now time.Time) bool {
	entries, err := os.ReadDir(filepath.Join(config.Home(), "jobs"))
	if err != nil && !errors.Is(err, fs.ErrNotExist) || len(entries) > 0 {
		return false
	}
	state := filepath.Join(config.Home(), "state")
	if watch, _ := run.ReadJSON(filepath.Join(state, "watch.json")); watch != nil {
		if said := watch.Str("boot_id"); said != "" && host.BootID() != "" && said != host.BootID() {
			return false
		}
	}
	if home.Seatless() && len(tmux.Sessions(tmux.Own())) > 0 {
		return false
	}
	for _, seat := range home.records {
		if seat.retired(state, now) {
			return false
		}
	}
	for _, seat := range home.Seats {
		if seat.Warning != "" {
			return false
		}
		if seat.Checkout() != "" && gitcall.Declared(seat.Checkout(), "features") != "" {
			return false
		}
	}
	return true
}

// retired is whether maintenance would forget its record (orch.sweep): a week after its panes exited
// where tmux holds it, else after the owner's stop or, with none, its last sighting.  An asleep
// seat is kept; a question unread keeps one too, which this does not read, so such a home waits on
// Python.
func (seat Seat) retired(state string, now time.Time) bool {
	read := func(kind, key string) any {
		if file, _ := run.ReadJSON(filepath.Join(state, kind+"-"+seat.Name+".json")); file != nil {
			return file.Get(key)
		}
		return nil
	}
	since := read("seat", "stopped_at")
	if seat.live || seat.held {
		since = read("session", "exited_since")
	} else if at, _ := number(since); at == 0 {
		since = read("session", "seen")
	}
	at, ok := number(since)
	return !seat.asleep && ok && at > 0 && at <= seconds(now)-stale
}
