package seat

import (
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// exitedPane is what tmux says of a session whose pane has exited: the session's id, the pane's
// and the second it died.
var exitedPane = regexp.MustCompile(`^\$[0-9]+ %[0-9]+ [0-9]+$`)

// Sweep is Python's orch.sweep, which the tick's seat sweep row and the ak screen's opening both
// run, each line it says to log: the side sessions seats started closed (closeSideSessions), then
// every seat a week past its going forgotten, as `ak orch stop` forgets one it stopped already.
// One a run still owns, one whose question is unread and one asleep stay.  The home is read as the
// tick reads it (TickHome): a live seat, which the sweep never touches, decides nothing here.
// False where Go does not read the home, or at the first seat whose harness keeps what Go does not forget, before
// anything of that seat is written or closed: what came before stands, and Python's next sweep
// finds it done.
func Sweep(now time.Time, log func(string)) (bool, error) {
	home, known := TickHome(now)
	owned, read := unfinished()
	if !known || !read {
		return false, nil
	}
	closeSideSessions(now, log)
	state := filepath.Join(config.Home(), "state")
	for _, seat := range home.records {
		went := seat.wentAt(state)
		path := filepath.Join(state, "session-"+seat.Name+".json")
		info, err := os.Lstat(path)
		if seat.live || seat.asleep || went <= 0 || went > seconds(now)-stale || slices.Contains(owned, seat.Name) || unread(state, seat.Name) ||
			err != nil || !info.Mode().IsRegular() {
			continue
		}
		record, err := run.ReadJSON(path)
		if err != nil || record == nil {
			continue
		}
		// what its harness kept goes with the seat, in forget
		if _, carried := harness.Forgetting(seat.own, record); !carried {
			return false, nil
		}
		word := "gone"
		if seat.held {
			word = "exited"
		}
		if !seat.held && !tmux.Absent(tmux.Own(), "="+seat.Name) || seat.held && !retireExited(seat.Name, now) {
			continue
		}
		log("forgot the session " + seat.Name + ", " + word + " for " + span(seconds(now)-went))
		if err := forget(state, seat.Name, log); err != nil {
			return true, err
		}
	}
	return true, nil
}

// wentAt is when a seat's week began: its panes' exit where tmux holds it, else the owner's stop
// or, with none, its last sighting, so a seat long gone from tmux that the owner stops today keeps
// its row the whole week; 0 where nothing dates it.
func (seat Seat) wentAt(state string) float64 {
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
	at, _ := number(since)
	return at
}

// unfinished are the seats runs still own (transitions.unfinished, read without supersession):
// one working, or one awaiting a recovery nobody acknowledged, launched from them.  False where
// a run record does not read.
func unfinished() ([]string, bool) {
	var owned []string
	read := run.Every(func(_ string, record *run.Object) bool {
		wait := record.Dict("waiting_on")
		lined := record.Str("state") == "waiting" && wait != nil && wait.Truthy("line") // the lander's
		if run.Active(record) || run.NeedsRecovery(record) && !lined && !record.Truthy("recovery_acknowledged_at") {
			owned = append(owned, run.Seat(record))
		}
		return true
	})
	return owned, read
}

// unread is orch.unread_question: the seat's notice is a question nobody has seen, or does not
// read, and might be one.
func unread(state, name string) bool {
	path := filepath.Join(state, "notify-"+name+".json")
	if _, err := os.Lstat(path); err != nil {
		return false
	}
	notice, err := run.ReadJSON(path)
	return err != nil || notice == nil || notice.Get("kind") == "needs" && !notice.Truthy("seen")
}

// retireExited ends the session of a seat whose pane died a week ago (orch.retire_exited), tmux
// itself rechecking in the command that ends it that the same pane is its only one, dead,
// unattached, in a session ak opened.  An unfamiliar layout or a failed probe never ends one.
func retireExited(name string, now time.Time) bool {
	target := "=" + name + ":"
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", target, "#{session_id} #{pane_id} #{pane_dead_time}")
	if err != nil || !exitedPane.MatchString(said) {
		return false
	}
	parts := strings.Fields(said)
	if died, err := strconv.ParseFloat(parts[2], 64); err != nil || seconds(now)-died < stale {
		return false // a respawn may have exited since the record's stamp
	}
	condition := "#{pane_dead}"
	for _, term := range []string{"#{==:#{session_attached},0}", "#{==:#{session_windows},1}", "#{==:#{window_panes},1}",
		"#{==:#{" + tmux.Mark + "},1}", "#{==:#{session_id}," + parts[0] + "}", "#{==:#{pane_id}," + parts[1] + "}",
		"#{==:#{pane_dead_time}," + parts[2] + "}"} {
		condition = "#{&&:" + condition + "," + term + "}"
	}
	_, err = tmux.Ask(tmux.Own(), "if-shell", "-F", "-t", target, condition, "kill-session -t "+commandhelp.ShellJoin([]string{"=" + name}))
	return err == nil && tmux.Absent(tmux.Own(), "="+name)
}
