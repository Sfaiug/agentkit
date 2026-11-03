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

// Looked is the seat as a frame draws it: its look where its panes still run, else as read.
func (seat Seat) Looked() (Seat, error) {
	if !seat.live {
		return seat, nil
	}
	return LookedLive(filepath.Join(config.Home(), "state"), seat.Name)
}

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

// Said is what opens under its row: its question, or an idle seat's way back in.
func (seat Seat) Said() string { return seat.reason }

// ModelName is the full name of the model it runs.
func (home Home) ModelName(seat Seat) string {
	return config.ModelName(seat.Orchestrator, home.models)
}

// Settled is whether the ak screen's first frame would leave this home as it is: what menu.main does
// first would change nothing but the two things that decide nothing.  With no boot_id,
// resume_after_boot only writes a baseline; and the tick stamps the seats' retention clocks as the
// menu does, a record holding its stamp being one Looking refuses.  A run, whatever its state, is
// one maintenance reaps or sweeps once; a stopped seat a week old it retires; a stranger on ak's
// server it may save and close; another boot's mark it resumes after.  A project naming its feature
// switches has Python run its command, and a job draws a line Go has no port of.
func (home Home) Settled(now time.Time) bool {
	for _, dir := range []string{run.Runs(), filepath.Join(config.Home(), "jobs")} {
		entries, err := os.ReadDir(dir)
		if err != nil && !errors.Is(err, fs.ErrNotExist) || len(entries) > 0 {
			return false
		}
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
	for _, seat := range home.Seats {
		if seat.Warning != "" {
			return false
		}
		if file, _ := run.ReadJSON(filepath.Join(state, "seat-"+seat.Name+".json")); file != nil {
			if at, ok := number(file.Get("stopped_at")); ok && at > 0 && at <= seconds(now)-stale {
				return false
			}
		}
		if seat.Checkout() != "" && gitcall.Declared(seat.Checkout(), "features") != "" {
			return false
		}
	}
	return true
}
