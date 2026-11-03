package seat

import (
	"context"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
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

// A Live is a seat its panes run on, as the tick reads it before any of its rows writes: what a look
// would find on its screen and in its conversation, and the word its ladder would decide of that.
type Live struct {
	Name, Own, Word string // its name, the harness its screen is read as, and its word
	State           string // what the look finds it doing, and since when
	Began           any
	Stall, Login    any      // the error the tick would type it back past, and its harness's words for a login out
	Stuck           bool     // what it stopped on is login trouble or a blocked operation (watch.stuck_on)
	Bound           bool     // its session names the pane its launch created (orch.bind_pane has done its work)
	Attached        bool     // a client is in it
	Path            string   // where tmux says its session works
	Draft           string   // what its composer holds, whitespace aside: "" for nothing, or no composer found
	Typed           []string // the lines ak typed there last, whitespace aside, that its draft is all of
	Title           any      // its conversation's custom title: "" for none, nil where none is read
	WrappedUp       bool     // its harness ended its last turn for a spent subscription (watch.limit_ended)
	Record, File    *run.Object
}

// Lives is every seat the home holds, each read as Live reads it; false where any record is not a
// seat its panes run on that Go reads.  A home with no record holds none where tmux holds no seat.
func Lives(now time.Time) ([]Live, bool) {
	if len(config.SeatFiles()) == 0 {
		return nil, OnNoServer()
	}
	home, known := Looking(now)
	if !known || len(home.Seats) != len(home.records) {
		return nil, false
	}
	state := filepath.Join(config.Home(), "state")
	var lives []Live
	for _, each := range home.records {
		live, ok := each.dry(state, now)
		if !ok {
			return nil, false
		}
		lives = append(lives, live)
	}
	return lives, true
}

// dry is the seat as Live reads it, false where its panes no longer run its harness or its screen
// reads blank, which says nothing.
func (seat Seat) dry(state string, now time.Time) (Live, bool) {
	record, _ := run.ReadJSON(filepath.Join(state, "session-"+seat.Name+".json"))
	file, _ := run.ReadJSON(filepath.Join(state, "seat-"+seat.Name+".json"))
	if file == nil {
		file = run.NewObject()
	}
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+seat.Name+":",
		"#{session_attached}\t#{"+tmux.HarnessPane+"}\t#{session_path}")
	session := strings.SplitN(said, "\t", 3)
	if !seat.live || record == nil || err != nil || len(session) != 3 {
		return Live{}, false
	}
	pane, exited := harnessScreen(seat.Name)
	if exited || strings.TrimFunc(pane, config.Space) == "" {
		return Live{}, false
	}
	at := seconds(now)
	found, _ := observed(state, seat.Name, seat.own, pane, at)
	decided, err := climbingOf(state, seat, found, at).climb()
	if err != nil {
		return Live{}, false
	}
	seen, tail := eyeOf(seat.own), screen.Tail(pane)
	conversation, cwd, account := record.Str("conversation"), record.Str("cwd"), record.Str("account")
	recorded, kept := harness.RecordedError(seat.own, conversation, cwd, account)
	line := recorded
	if !kept {
		line = outputLine(seen.rules.Said(tail))
	}
	draft, drawn := seen.rules.ComposerDraft(pane)
	if !drawn {
		draft = ""
	}
	title, _ := harness.SessionTitle(seat.own, record, ownFile("title", seat.Name))
	wrapped := harness.WrappedUp(seat.own, map[string]any{"conversation": conversation, "cwd": cwd, "account": record.Get("account")},
		func(entry *run.Object) bool { return script.Prompted(seat.own, entry).Text != "" })
	return Live{Name: seat.Name, Own: seat.own, Word: decided.word, State: found.state, Began: found.began,
		Stall: seen.stallOn(seat.own, pane, tail, recorded, kept), Login: seen.loginOn(seat.own, tail, recorded, kept),
		Stuck: loginHint.MatchString(line) || terminalFailure.MatchString(line),
		Bound: session[1] != "", Attached: session[0] != "" && session[0] != "0", Path: session[2],
		Draft: draft, Typed: joined(seat.Name, draft), Title: title, WrappedUp: script.Moment(wrapped) != 0, Record: record, File: file}, true
}

// Health is the tick's look at a seat its panes run on where it has nothing to recover
// (watch.health): its conversation's title read on from where the last reading stopped, then
// watch.live_state's look and the word published, as announce_state publishes it with no look of
// its own, so what its last answer moved stays as it is.
func Health(name string) error {
	state := filepath.Join(config.Home(), "state")
	models, err := config.Models()
	if err != nil {
		return err
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
		return err
	}
	_, err = lookedLive(state, name, false)
	return err
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
