package seat

import (
	"cmp"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/screen"
	"agentkit/internal/terminal"
	"agentkit/internal/tmux"
)

// turnSeconds is the age past which a turn's reason says how long it has run (watch.TURN_SECS).
const turnSeconds = 3 * 3600

// An eye is what one harness's seats are read with, compiled once, when a look first needs that
// harness's manifest: whether it can be read at all is known before anything is written.
type eye struct {
	rules   *screen.Rules
	wrapper *regexp.Regexp // the auth wrapper its login errors open with
	bad     error
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
	if err = cmp.Or(err, ruled, authed); err != nil {
		return eye{bad: err}
	}
	found := eye{}
	if found.rules, err = screen.Compile(chrome, rules); err != nil {
		return eye{bad: err}
	}
	if wrapper, _ := auth["wrapper"].(string); wrapper != "" {
		if found.wrapper, err = screen.Pattern(wrapper, "(?i)"); err != nil {
			return eye{bad: err}
		}
	}
	return found
}

// looksOn is whether Go reads a seat its panes still run on, one of that harness: one whose screen
// it reads and whose rules it can say, the owner's stop mark gone.  What else its word would hang on
// reading refuses for every seat: a hook fact, a notice, a plan, a run, a login out.
func (seat Seat) looksOn(own string) bool {
	return harness.Looks(own) && eyeOf(own).bad == nil && !seat.closed
}

// A sight is what a look found on the seat's screen, watch.classify's with no hook fact beside it,
// and the error it shows at its prompt.
type sight struct {
	state, authority, rule, evidence string
	since, began, stall, login       any
}

// sighted classifies the captured pane against the seat file as it stood.
func sighted(found screen.Reading, previous *run.Object, now float64) sight {
	if found.State == "" {
		// nothing said anything: never `working` without evidence, and nothing knows since when
		return sight{state: "at_prompt", rule: "none", evidence: "no hook fact and no screen rule matched"}
	}
	var began any = run.Float(now)
	opened, dated := run.Num(previous.Get("opened_at"))
	_, carried := run.Num(previous.Get("began"))
	switch {
	case previous.Str("state") == found.State && carried:
		began = previous.Get("began")
	case previous.Get("state") == nil && dated && opened <= now:
		// first sight: it has been so at least since it was last opened
		began = previous.Get("opened_at")
	}
	return sight{state: found.State, authority: "screen", rule: found.Rule, evidence: found.Evidence, since: began, began: began}
}

// look is watch.look_at: one capture, classified and kept as watch.live_state keeps it.  A blank
// capture says nothing of the screen, so it writes nothing.
func (seat Seat) look(state string, now float64) (sight, error) {
	previous, _ := run.ReadJSON(filepath.Join(state, "seat-"+seat.Name+".json"))
	if previous == nil {
		previous = run.NewObject()
	}
	record, _ := run.ReadJSON(filepath.Join(state, "session-"+seat.Name+".json"))
	if record == nil {
		record = run.NewObject()
	}
	own := seat.own
	seen := eyeOf(own)
	pane, _ := tmux.Ask(tmux.Own(), "capture-pane", "-p", "-e", "-J", "-t", "="+seat.Name+":")
	tail := screen.Tail(pane)
	found := sighted(seen.rules.Read(tail), previous, now)
	if pane == "" {
		found.stall, found.login = previous.Get("stall"), previous.Get("login")
		return found, nil
	}
	if found.state == "at_prompt" {
		said, recorded := harness.RecordedError(own, record.Str("conversation"), record.Str("cwd"))
		found.stall = seen.stallOn(own, pane, tail, said, recorded)
		found.login = seen.loginOn(own, tail, said, recorded)
	}
	fields := []field{{"state", found.state}, {"since", found.since}, {"began", found.began}, {"authority", found.authority},
		{"rule", found.rule}, {"evidence", found.evidence}, {"hooked", nil}, {"hooked_at", nil}, {"hooked_event", nil},
		{"interrupted", false}, {"stall", found.stall}, {"login", found.login}}
	return found, writeSeat(state, seat.Name, append(fields, turnMarks(seen.rules, tail, found, previous, now)...))
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
	var output []string
	for _, line := range rules.Said(tail) {
		if !promptOpened.MatchString(line) {
			output = append(output, line)
		}
	}
	said := config.Fold(strings.Join(output, " "))
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

// decided sets the word of a seat with nothing but its screen to say what it is, the rungs of
// watch._session_state the rest of what Read knows leaves: a question on its screen, a turn in
// flight, an error the tick types it back past, and at rest otherwise.  Typed text nobody sent is
// no word of its own: it goes beside it, once nobody is in the seat to see it.
func (seat *Seat) decided(found sight, now float64, attached bool) {
	seat.Word, seat.reason, seat.since = "idle", "", found.began
	seat.question = false
	switch {
	case found.state == "asking":
		seat.Word, seat.reason, seat.question = "needs you", cmp.Or(config.Fold(found.evidence), "waiting for you"), true
	case found.state == "working":
		seat.Word = "working"
		if began, ok := run.Num(found.began); ok && now-began > turnSeconds {
			seat.reason = "turn running " + terminal.FormatAge(now-began)
		}
	case found.stall != nil:
		seat.Word, seat.reason = "working", fmt.Sprintf("retrying: %v", found.stall)
	}
	seat.unsent = ""
	if found.state == "draft" && !attached {
		seat.unsent = config.Fold(found.evidence)
	}
	said := ""
	switch {
	case found.state == "asking" || found.state == "draft":
		said = found.evidence
	case found.stall != nil:
		said, _ = found.stall.(string)
	case found.login != nil:
		said, _ = found.login.(string)
	}
	seat.wordFrom = []any{found.state, found.rule, said}
}

// explainLive is orch.explain of a seat its panes still run on, under its announce lock from the
// look to the word: watch.announce_state's look, what its last answer moved, the word published,
// and what decided it read back as every other reader reads it.
func (seat Seat) explainLive(state string, models map[string]config.Model) ([]string, error) {
	err := announcing(state, seat.Name, func() error {
		now := time.Now()
		found, err := seat.look(state, seconds(now))
		if err != nil {
			return err
		}
		attached, _ := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+seat.Name+":", "#{session_attached}")
		seat.decided(found, seconds(now), attached != "" && attached != "0")
		return seat.announced(state, now, models)
	})
	if err != nil {
		return nil, err
	}
	file, _ := run.ReadJSON(filepath.Join(state, "seat-"+seat.Name+".json"))
	if file == nil {
		file = run.NewObject()
	}
	return []string{seat.Name + "  " + seat.Word, "  reason:    " + cmp.Or(seat.reason, "-"),
		"  authority: " + cmp.Or(file.Str("authority"), "default") + "  rule: " + cmp.Or(file.Str("rule"), "-"),
		"  evidence:  " + cmp.Or(file.Str("evidence"), "nothing on the screen said otherwise"),
		"  since:     " + sinceLine(file.Get("word_since"), time.Now())}, nil
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
