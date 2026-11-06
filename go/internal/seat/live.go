package seat

import (
	"context"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/lock"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/screen"
	"agentkit/internal/tmux"
	script "agentkit/internal/transcript"
)

// terminalFailure is an error that blocks an operation, not one a final answer may name
// (watch.TERMINAL_FAILURE).
var terminalFailure = regexp.MustCompile(`(?i)\b(?:cannot|can't|unable to) (?:proceed|continue)\b|` +
	`\b(?:session|connection|stream|transport)\b.*\b(?:closed|lost|terminated)\b|\bunexpected status [45]\d\d\b`)

// A Live is a seat its panes run on, as one capture shows it: what a look would find on its screen
// and in its conversation, read with nothing written.
type Live struct {
	Name, Own    string // its name, and the harness its screen is read as
	State        string // what the look finds it doing, and since when
	Began        any
	Stall, Login any      // the error the tick would type it back past, and its harness's words for a login out
	Stuck        bool     // what it stopped on is login trouble or a blocked operation (watch.stuck_on)
	Refused      string   // the refusal by its window its conversation's record ends on, which watch.seat_account takes
	Bound        bool     // its session names the pane its launch created (orch.bind_pane has done its work)
	Attached     bool     // a client is in it
	Path         string   // where tmux says its session works
	Pane         string   // the capture itself, whose changes age a stall (watch.observe)
	Draft        string   // what its composer holds, whitespace aside: "" for nothing, or no composer found
	Typed        []string // the lines ak typed there last, whitespace aside, that its draft is all of
	Title        any      // its conversation's custom title: "" for none, nil where none is read
	WrappedUp    bool     // its harness ended its last turn for a spent subscription (watch.limit_ended)
	Record, File *run.Object
}

// Seats is the name of every seat the home holds but a legacy one, another program's session that
// the tick never cards, looks at or types into; false where any record is not a seat Go reads.
// A home with no record holds none where tmux holds no seat.
func Seats(now time.Time) ([]string, bool) {
	home, known := seated(now)
	var names []string
	for _, each := range home.Seats {
		if !each.legacy {
			names = append(names, each.Name)
		}
	}
	return names, known
}

// Lives reads the live seats, leaving absent seats and dead panes to the rows that read them.
func Lives(now time.Time) ([]Live, bool) {
	home, known := seated(now)
	if !known {
		return nil, false
	}
	state := filepath.Join(config.Home(), "state")
	var lives []Live
	for _, each := range home.Seats {
		if !each.looked() { // no pass types into a seat nothing here started
			continue
		}
		pane, exited := harnessScreen(each.Name)
		if exited {
			continue
		}
		found, _ := observed(state, each.Name, each.reader, pane, seconds(now))
		live, ok := each.lived(state, pane, exited, found, now)
		if !ok {
			return nil, false
		}
		lives = append(lives, live)
	}
	return lives, true
}

// seated is the home, false where any record or seat is one Go does not read.
func seated(now time.Time) (Home, bool) {
	if len(config.SeatFiles()) == 0 && strangers() {
		return Home{}, false
	}
	return TickHome(now)
}

// lived is the seat as Live reads it off that capture, false where its panes no longer run its
// harness or its ladder cannot be climbed. A starting harness's blank screen says no more
// than its unknown screen rule; its going run can still decide its word.
func (seat Seat) lived(state, pane string, exited bool, found sight, now time.Time) (Live, bool) {
	record, _ := run.ReadJSON(filepath.Join(state, "session-"+seat.Name+".json"))
	file, _ := run.ReadJSON(filepath.Join(state, "seat-"+seat.Name+".json"))
	if file == nil {
		file = run.NewObject()
	}
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+seat.Name+":",
		"#{session_attached}\t#{"+tmux.HarnessPane+"}\t#{session_path}")
	session := strings.SplitN(said, "\t", 3)
	if !seat.live || record == nil || err != nil || len(session) != 3 || exited {
		return Live{}, false
	}
	if !liveClimbs(state, seat, found, seconds(now)) {
		return Live{}, false
	}
	seen, tail := eyeOf(seat.own), screen.Tail(pane)
	conversation, cwd := record.Str("conversation"), record.Str("cwd")
	recorded, kept := seat.reader.RecordedError(record)
	line, refused := recorded, ""
	if !kept {
		line = outputLine(seen.rules.Said(tail))
	} else if window, _ := harness.Refusal(seat.own, recorded); window {
		refused = recorded
	}
	draft, drawn := seen.rules.ComposerDraft(pane)
	if !drawn {
		draft = ""
	}
	title, _ := harness.SessionTitle(seat.own, record, ownFile("title", seat.Name))
	wrapped := harness.WrappedUp(seat.own, map[string]any{"conversation": conversation, "cwd": cwd, "account": record.Get("account")},
		func(entry *run.Object) bool { return script.Prompted(seat.own, entry).Text != "" })
	return Live{Name: seat.Name, Own: seat.own, State: found.state, Began: found.began,
		Stall: seen.stallOn(seat.own, pane, tail, recorded, kept), Login: seen.loginOn(seat.own, tail, recorded, kept),
		Stuck: loginHint.MatchString(line) || terminalFailure.MatchString(line), Refused: refused,
		Bound: session[1] != "", Attached: session[0] != "" && session[0] != "0", Path: session[2], Pane: pane,
		Draft: draft, Typed: joined(seat.Name, draft), Title: title, WrappedUp: harness.Moment(wrapped) != 0, Record: record, File: file}, true
}

// Health is the tick's look at a seat its panes run on (watch.health): its conversation's title read
// on from where the last reading stopped, then under its announce lock one capture, read as Live
// reads it. Both ok and the account decision run before that capture is kept and its word
// published, so unsupported recovery leaves no publish behind. The account decision may reopen
// the seat through its shared launch path; a refusal its record ends on, or its one subscription
// spent, is instead waited on, the wait written before the publish (waitOnUsage). False where
// either decision leaves work to Python.
func Health(name string, ok func(Live) bool, log func(string)) (bool, error) {
	state := filepath.Join(config.Home(), "state")
	models, err := config.Models()
	if err != nil {
		return false, err
	}
	// read under its typing lock, as watch.follow_title reads it
	err = notify.Held(context.Background(), name, func(current string) error {
		record, _ := run.ReadJSON(filepath.Join(state, "session-"+current+".json"))
		if record == nil {
			return nil
		}
		cache := ownFile("title", current)
		if _, kept := harness.SessionTitle(models[record.Str("orchestrator")].Harness, record, cache); kept != nil {
			return harness.KeepTitle(cache, kept)
		}
		return nil
	})
	if err != nil {
		return false, err
	}
	carried := false
	// that wait is written under every lifecycle change's lock, which watch.seat_account takes
	// outside the announce lock, the meters read before either
	readings, ahead := usageAhead(state, name, models)
	if ahead {
		held, err := lock.Wait(context.Background(), filepath.Join(state, "watch.lock"))
		if err != nil {
			return false, err
		}
		defer held.Close()
	}
	err = announcing(state, name, func() error {
		now := time.Now()
		home, seat, known := liveSeat(name, now, nil, true)
		if !known {
			carried, err = home.healthGone(state, name, now)
			return err
		}
		if carried = !seat.looked(); carried { // a seat nothing here started
			return nil
		}
		pane, exited := harnessScreen(name)
		if exited {
			carried, err = home.healthDied(state, name, now)
			return err
		}
		found, previous := observed(state, name, seat.reader, pane, seconds(now))
		live, read := seat.lived(state, pane, exited, found, now)
		if carried = read && ok(live); !carried {
			return nil
		}
		var wait func() error
		blank := strings.TrimFunc(pane, config.Space) == ""
		// a capture that came back blank is no look to follow; the account decisions read the
		// model followed, as watch.health's seat_model does, decided before the move is written
		model := live.Record.Str("orchestrator")
		if !blank && seat.follow.chosen != "" {
			model = seat.follow.chosen
		}
		if due := live.Refused != "" || spentAlone(model, home.models[model]); due || ahead {
			// watch.seat_account waits it out whatever the screen shows: behind a blank one, Python's,
			// as is one watch.lock was taken ahead for, or not, on a model the look no longer follows:
			// no wait is written without that lock, and no account moved under it, as the move takes it
			if carried = due && readings != nil && !blank; carried {
				wait, carried = seat.waitOnUsage(state, live, model, found, readings, now, log)
			}
			if !carried {
				return nil
			}
		}
		if !blank {
			if err := seat.moved(state, home.models); err != nil {
				return err
			}
			if record, _ := run.ReadJSON(filepath.Join(state, "session-"+seat.Name+".json")); record != nil {
				live.Record = record
			}
			// a record changed meanwhile took no move, and its wait is Python's
			if carried = wait == nil || live.Record.Str("orchestrator") == model; !carried {
				return nil
			}
		}
		if blank && found.authority != "hook" && !seat.hasActiveRun() {
			return nil
		}
		if wait == nil { // a refusal is waited on, never moved from at its prompt
			if carried, err = MoveAccount(live, log); !carried || err != nil {
				return err
			}
		}
		found, err := seat.keep(state, pane, exited, found, previous, seconds(now))
		if err != nil {
			return err
		}
		if err := seat.askKeptBack(found); err != nil {
			return err
		}
		if wait != nil {
			if err := wait(); err != nil {
				return err
			}
		} else if live.sameRecord() { // A relaunch consumed the old Stop; it cannot nudge the replacement harness.
			// an unanswered owner decision is never a reason to type a resume
			asked := notify.OwnerQuestion(notify.Last(seat.Name))
			if found, err = seat.nudgeQuestion(state, found, log); err == nil && !asked {
				found, err = seat.nudgeOpenWork(state, found, log)
			}
			if err != nil {
				return err
			}
		}
		if err := seat.decided(state, found, seconds(now), live.Attached); err != nil {
			return err
		}
		return seat.published(state, now, home.models)
	})
	return carried, err
}

// Published is the word the seat's file holds and since when, as its last announce wrote them.
func Published(name string) (word string, since any) {
	file, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "seat-"+name+".json"))
	if file == nil {
		return "", nil
	}
	return file.Str("word"), file.Get("word_since")
}

// Update changes a seat's record under its lock, as config.update_session does, only where change
// says it changed it; a record removed or renamed meanwhile is left alone.
func Update(name string, change func(record *run.Object) bool) error {
	return update(filepath.Join(config.Home(), "state"), name, change)
}

// joined is the lines ak typed into the seat last, whitespace aside, that held is all of, joined in
// order, else none: a harness that draws a line late joins it to the next ak types (watch._joined).
func joined(name, held string) []string {
	var typed, lines []string
	for sent := range script.Entries(ownFile("input", name)) {
		typed = append(typed, screen.Unspaced(sent.Str("text")))
	}
	for len(typed) > 0 && len(strings.Join(lines, "")) < len(held) {
		lines = append([]string{typed[len(typed)-1]}, lines...)
		typed = typed[:len(typed)-1]
	}
	if held == "" || strings.Join(lines, "") != held {
		return nil
	}
	return lines
}
