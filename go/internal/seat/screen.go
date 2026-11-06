package seat

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/pyre"
	"agentkit/internal/run"
	"agentkit/internal/screen"
	"agentkit/internal/tmux"
)

// turnSeconds is the age past which a turn's reason says how long it has run (watch.TURN_SECS).
const turnSeconds = 3 * 3600

// An eye is what one harness's seats are read with, compiled once, when a look first needs that
// harness's manifest: whether it can be read at all is known before anything is written.
type eye struct {
	rules     *screen.Rules
	wrapper   *pyre.Regexp   // the auth wrapper its login errors open with
	authority map[string]any // which states its hooks decide, and which its screen
	bad       error
}

var eyes sync.Map

func eyeOf(name string) eye {
	if known, ok := eyes.Load(name); ok {
		return known.(eye)
	}
	found := compileEye(name)
	eyes.Store(name, found)
	return found
}

func compileEye(name string) eye {
	chrome, err := config.Section(name, "screen")
	rules, ruled := config.ScreenRules(name)
	auth, authed := config.Section(name, "auth")
	authority, read := config.Section(name, "authority")
	if err = cmp.Or(err, ruled, authed, read); err != nil {
		return eye{bad: err}
	}
	found := eye{authority: authority}
	if found.rules, err = screen.Compile(chrome, rules); err != nil {
		return eye{bad: err}
	}
	if wrapper, _ := auth["wrapper"].(string); wrapper != "" {
		if found.wrapper, err = pyre.Compile(wrapper, pyre.IgnoreCase); err != nil {
			return eye{bad: err}
		}
	}
	return found
}

// looksOn is whether Go reads a seat its panes still run on, one of that harness: one whose screen
// it reads and whose rules it can say, the owner's stop mark gone.  What else its word would hang on,
// its ladder's rungs say.
func (seat Seat) looksOn(own string) bool {
	return harness.Looks(own) && eyeOf(own).bad == nil && !seat.closed
}

// A sight is what a look found of a seat, watch.classify's, and the error it shows at its prompt.
type sight struct {
	state, authority, rule, evidence string
	since, began, stall, login       any
	hooked, hookedEvent              string // what the hook alone said, kept where a rule overrode it, and which event
	hookedAt                         any
	interrupted                      bool // the owner stopped its last turn: until their next prompt it rests
	typedByAk                        bool // its composer holds the line ak typed last, not the owner's
	holds                            []string
	heldRead                         bool // its screen said what it holds, none or some: else the last read stands
}

// observed is watch.observed: what a capture shows of a seat, against its files as they stand,
// writing nothing.  A blank capture says nothing of the error it shows.
func observed(state, name string, reader harness.Reader, pane string, now float64) (found sight, previous *run.Object) {
	previous, _ = run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	if previous == nil {
		previous = run.NewObject()
	}
	record, _ := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	if record == nil {
		record = run.NewObject()
	}
	own := reader.Name
	seen := eyeOf(own)
	tail := screen.Tail(pane)
	fact := reader.HookFact(name)
	found = classify(own, seen.rules.Read(pane), fact, previous, now, endedAt(name, own, record, seen.rules, pane, fact, now))
	found.typedByAk = found.state == "draft" && typedByAk(name, seen.rules, pane)
	found.holds, found.heldRead = seen.rules.Held(tail)
	switch {
	case pane == "":
		found.stall, found.login = previous.Get("stall"), previous.Get("login")
	case found.state == "at_prompt":
		said, recorded := reader.RecordedError(record)
		found.stall = seen.stallOn(own, pane, tail, said, recorded)
		found.login = seen.loginOn(own, tail, said, recorded)
	}
	return found, previous
}

// harnessScreen is what the pane a seat's launch created shows, whichever window is active, or where
// that pane was removed the session's current one, as older launches used (orch.harness_pane); and
// whether its harness has exited, when the last frame it left is no turn in flight and it shows nothing.
func harnessScreen(name string) (shown string, exited bool) {
	target := "=" + name + ":"
	said, _ := tmux.Ask(tmux.Own(), "list-panes", "-s", "-t", target, "-f", "#{==:#{pane_id},#{"+tmux.HarnessPane+"}}", "-F", "#{pane_id} #{pane_dead}")
	pane, dead, saved := strings.Cut(said, " ")
	if dead == "1" {
		return "", true
	}
	if saved {
		target = pane
	}
	return captureHarness(target)
}

// look is watch.look_at: one capture, classified and kept; none of a screen nobody reads.
func (seat Seat) look(state string, now float64) (sight, error) {
	if !seat.looked() {
		return sight{}, nil
	}
	pane, exited := harnessScreen(seat.Name)
	found, previous := observed(state, seat.Name, seat.reader, pane, now)
	if err := seat.keepHolds(state, found); err != nil {
		return found, err
	}
	return seat.keep(state, pane, exited, found, previous, now)
}

// keepHolds keeps the background work the capture shows running where it shows the list at all:
// unread work is no evidence none runs, so the last read stands (watch.observed).  Kept before
// anything acts on the look, as Python's look keeps it: a relaunch after clears it, and nothing
// puts the ended process's work back.
func (seat Seat) keepHolds(state string, found sight) error {
	if !found.heldRead {
		return nil
	}
	return writeSeat(state, seat.Name, []field{{"holds", modelList(found.holds)}})
}

// keep is what a capture found kept as watch.live_state keeps it.  A blank capture says nothing of
// the screen, so it writes nothing but what a hook decided; a harness that exited does say: the
// error it was retrying past ended with it.
func (seat Seat) keep(state, pane string, exited bool, found sight, previous *run.Object, now float64) (sight, error) {
	if exited {
		return seat.keepExited(state, found)
	} else if pane == "" && found.authority != "hook" {
		return found, nil
	}
	seen, tail := eyeOf(seat.own), screen.Tail(pane)
	fields := []field{{"state", found.state}, {"since", found.since}, {"began", found.began}, {"authority", found.authority},
		{"rule", found.rule}, {"evidence", found.evidence}, {"hooked", orNone(found.hooked)}, {"hooked_at", found.hookedAt}, {"hooked_event", orNone(found.hookedEvent)},
		{"interrupted", found.interrupted}, {"stall", found.stall}, {"login", found.login}}
	return found, seat.save(state, append(fields, turnMarks(seen.rules, tail, found, previous, now)...))
}

// orNone is that text, or null for none, as the seat file keeps what a hook did not say.
func orNone(text string) any {
	if text == "" {
		return nil
	}
	return text
}

// promptOpened is a row opening on a prompt mark, which is input and no output.
var promptOpened = regexp.MustCompile(`^(?:│` + config.SpaceClass + `*)?[>›❯⟩]`)

// turnMarks is what this look adds to the marks the end-of-turn rule reads (watch.stop_marks):
// when the turn behind the screen began, as near as a look can say, and the words a seat at its
// prompt shows.  A dialog or a half-typed line ends no turn and begins none.
func turnMarks(rules *screen.Rules, tail string, found sight, previous *run.Object, now float64) []field {
	switch found.state {
	case "working":
		if previous.Str("state") == "working" {
			return nil
		}
		return []field{{"turn_began", found.began}}
	case "at_prompt":
	default:
		return nil
	}
	said := stopWords(rules, tail)
	spoke := !run.Equal(previous.Get("stop_said"), said)
	if !spoke && previous.Str("state") == "at_prompt" {
		return nil
	}
	marks := []field{{"stop_said", said}, {"stop_said_at", run.Float(now)}}
	if spoke || previous.Str("state") == "working" {
		seen, dated := run.Num(previous.Get("stop_said_at"))
		began, known := run.Num(previous.Get("turn_began"))
		if dated && (!known || seen > began) {
			marks = append(marks, field{"turn_began", previous.Get("stop_said_at")})
		}
	}
	return marks
}

// ErrUnread is a seat that came to hold what Go does not read yet while its look waited: Python's
// to answer, with nothing written.
var ErrUnread = errors.New("Go does not read this seat yet")

// liveSeat is the home and the seat by that name, where Go reads them and its panes still run on.
func liveSeat(name string, now time.Time, runs readsRuns, readers recordReaders, pending ...bool) (Home, Seat, bool) {
	home, known := reading(now, true, runs, readers, pending...)
	at := slices.IndexFunc(home.Seats, func(each Seat) bool { return each.Name == name })
	if !known || at < 0 || !home.Seats[at].live {
		return home, Seat{}, false
	}
	return home, home.Seats[at], true
}

// LookedLive is the look at a seat its panes still run on, under its announce lock from the reading
// to the word, as the wait for that lock can outlast what the home held: watch.announce_state's
// look, what its last answer moved, and the word published.
func LookedLive(state, name string) (Seat, error) {
	return lookedLive(state, name, lookRuns, nil)
}

func lookedLive(state, name string, runs readsRuns, readers recordReaders) (Seat, error) {
	var seat Seat
	err := announcing(state, name, func() error {
		now := time.Now()
		home, live, known := liveSeat(name, now, runs, readers)
		if !known {
			return ErrUnread
		}
		seat = live
		found, err := seat.look(state, seconds(now))
		if err != nil {
			return err
		}
		if err := seat.askKeptBack(found); err != nil {
			return err
		}
		attached, _ := tmux.Ask(seat.server(), "display-message", "-p", "-t", "="+name+":", "#{session_attached}")
		if err := seat.decided(state, found, seconds(now), attached != "" && attached != "0"); err != nil {
			return err
		}
		return seat.announced(state, now, home.models)
	})
	return seat, err
}

// explainLive is orch.explain of a seat its panes still run on, from the look it just published.
func explainLive(state, name string, runs readsRuns, readers recordReaders) ([]string, error) {
	seat, err := lookedLive(state, name, runs, readers)
	if err != nil {
		return nil, err
	}
	return seat.Explanation(time.Now()), nil
}

// sinceLine is when a word began and how long ago, "unknown" where nothing knows.
func sinceLine(since any, now time.Time) string {
	at, ok := run.Num(since)
	if !ok {
		return "unknown"
	}
	return time.Unix(int64(at), 0).Format("2006-01-02 15:04") + " (" + span(seconds(now)-at) + " ago)"
}

// span is a length of time in the one unit that says the most about it (orch.span).
func span(length float64) string {
	secs := max(0, int64(length))
	switch {
	case secs >= 86400:
		return fmt.Sprintf("%dd", secs/86400)
	case secs >= 3600:
		return fmt.Sprintf("%dh", secs/3600)
	case secs >= 60:
		return fmt.Sprintf("%dm", secs/60)
	}
	return fmt.Sprintf("%ds", secs)
}
