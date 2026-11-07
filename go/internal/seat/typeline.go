package seat

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode"

	"agentkit/internal/config"
	"agentkit/internal/guard/keys"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/screen"
	"agentkit/internal/tmux"
	script "agentkit/internal/transcript"
)

const (
	keyGap   = 500 * time.Millisecond // text and Enter go separately (watch.KEY_GAP)
	sentWait = 5 * time.Second        // a typed line's time to show whole, and to leave (watch.SENT_WAIT)
	sentPoll = 500 * time.Millisecond
)

// errUntyped is a pass that put no line in.
var errUntyped = errors.New("no line went in")

var (
	paneID = regexp.MustCompile(`^%[0-9]+$`)
	escape = regexp.MustCompile(`\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])`)
)

// typeAtPrompt types one line into that seat, only while its harness sits at its own prompt with
// its composer read empty, through Python's confirmed send (watch.type_at_prompt): the prompt read
// again under the seat's typing lock right before the first key, the line's entry in its input
// file, its text, `receipt` handed the mark the ending keeps once the text is in, and an Enter only
// while the composer holds the line alone, then once more where the line did not leave.  True once
// the composer reads empty and its terminal holds no unread input.
//
// Go types only where its reads are Python's: a harness whose screen Go reads, a seat with no
// question kept back for its next turn and no text kept by ak's editor.  Anywhere else, a
// composer holding text among them, which Python's own editor types past, it puts nothing in and
// the line is the tick's.  No key goes in while the cursor is off its composer (offComposer).
func typeAtPrompt(name, line string, typed *run.Object, receipt func(mark *run.Object) error, log func(string), stale func(string) bool) bool {
	return typeAtPane(name, "", line, typed, receipt, log, stale)
}

// typeAtPane is typeAtPrompt into that pane, "" for the seat's window's own.
func typeAtPane(name, pane, line string, typed *run.Object, receipt func(mark *run.Object) error, log func(string), stale func(string) bool) bool {
	own, record := seatHarness(name)
	if !typable(own) {
		return false
	}
	if pane == "" {
		pane = "=" + name + ":"
	}
	pin := func(target string) ([]string, error) {
		said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", target, "#{pane_id}\t#{session_created}\t#{pane_pid}")
		return append(strings.Split(said, "\t"), "", ""), err
	}
	fields, err := pin(pane)
	pane = fields[0]
	if err != nil || !paneID.MatchString(pane) {
		return false
	}
	// A launch holding the send lock may respawn the pane while this pass waits for it: under the
	// lock, the pane runs the process it was pinned with, or the pass is stale.  Not its birth: a
	// pane linked into two sessions may answer with the other's.
	held := stale
	stale = func(current string) bool {
		now, err := pin(pane)
		return held(current) || err != nil || now[0] != pane || now[2] != fields[2]
	}
	text := keyed(line)
	// The birth is in whole seconds and a pane respawned in place keeps it: the pane's process
	// tells a harness started since, its composer empty, from the one the line went into.
	mark := run.Fields("line", text, "seat", created(fields[1]))
	if pid, err := strconv.Atoi(fields[2]); err == nil {
		mark.Set("pid", pid)
	}
	at := seatAt{name, own, pane}
	if typed != nil && run.Equal(typed, mark) {
		return at.finishTyped(text, stale, log)
	}
	if held, drawn := at.composer(); !drawn || held != "" || !at.takesLine() {
		return false
	}
	ready := func() bool { return at.holds(text) == "line" }
	err = notify.Held(context.Background(), name, func(current string) error {
		at.name = current
		if stale(current) || !at.quiet() || at.unasked() || at.editorKept() || at.unread() || at.offComposer() {
			return errUntyped
		}
		entry := typingReceipt(own, record, text)
		file, err := os.OpenFile(ownFile("input", current), os.O_RDWR|os.O_APPEND|os.O_CREATE, 0o666)
		if err != nil {
			return err
		}
		defer file.Close()
		before, err := file.Seek(0, 2)
		if err != nil {
			return err
		}
		// a restart between text and Enter must still know whose line is in the composer
		if _, err := file.WriteString(run.Line(entry) + "\n"); err != nil {
			return err
		}
		if out, err := keys.Type(pane, "-l", text); err != nil {
			file.Truncate(before)
			log("WARN could not type into the " + current + " seat: " + tail(out+err.Error(), 200))
			return errUntyped
		}
		if err := receipt(mark); err != nil {
			return err
		}
		time.Sleep(keyGap)
		if !poll(ready) || stale(current) || !at.enter(log) {
			return errUntyped
		}
		return nil
	})
	if err != nil {
		return false
	}
	if !poll(func() bool { return at.sent(text) }) {
		again := notify.Held(context.Background(), name, func(current string) error {
			at.name = current
			if stale(current) || !ready() || !at.enter(log) {
				return errUntyped
			}
			return nil
		})
		if again != nil {
			return false
		}
		if !poll(func() bool { return at.sent(text) }) {
			log("WARN " + at.name + ": typed text sits unsent in its composer: " + cutRunes(text, 60))
			return false
		}
	}
	return at.holds(text) == "empty" && !at.unread()
}

// typable is a harness Go types into: one whose screen it reads as Python does, and whose
// conversation it finds to count the prompts before a line.
func typable(own string) bool {
	if own == "" || !harness.Looks(own) || eyeOf(own).bad != nil {
		return false
	}
	_, _, known := script.Typed(own, nil, "")
	return known
}

// Watching is whether that seat is up for a line to go into, Python's orch.watching of a seat on
// ak's own server: tmux holds it as ak's, and its harness has not exited.
func Watching(name string) bool {
	for _, session := range tmux.Sessions(tmux.Own()) {
		if session.Name == name && session.Mark == "1" {
			_, exited := harnessScreen(name)
			return !exited
		}
	}
	return false
}

// Untyped is what a look at that seat read where no line went into it, watch.untyped: its state,
// what decided it and its composer, and whether it read at its prompt, which contradicts a line
// not taken, so that screen is kept for the cause to be read off it.
func Untyped(name string) (string, bool) {
	own, _ := seatHarness(name)
	at := seatAt{name: name, own: own, pane: "=" + name + ":"}
	shown := ""
	if own != "" && eyeOf(own).bad == nil {
		shown = at.capture()
	}
	if strings.TrimFunc(shown, unicode.IsSpace) == "" {
		return "its screen could not be read", false
	}
	found := at.sight(shown)
	held, drawn := eyeOf(own).rules.ComposerDraft(shown)
	rule := found.rule
	if rule == "" {
		rule = "nothing"
	}
	said := "it reads " + found.state + " by " + rule
	if found.hooked == "working" && found.state != "working" {
		said += ", its " + found.hookedEvent + " hook says its turn runs"
	}
	switch {
	case !drawn:
		said += ", its composer not found"
	case held == "":
		said += ", its composer empty"
	default:
		said += ", its composer holding text"
	}
	if !at.free(found) {
		return said, false
	}
	kept := ownFile("refused", name)
	if os.WriteFile(kept, []byte(shown), 0o666) != nil {
		return said, true
	}
	return said + "; its screen is kept in " + kept, true
}

// seatHarness is the harness of the model in that seat and its record, "" for a seat whose record
// names no model the config runs (watch.seat_model).
func seatHarness(name string) (string, map[string]any) {
	_, record, err := config.ResolveSession(name)
	models, unread := config.Models()
	orchestrator, _ := record["orchestrator"].(string)
	if err != nil || unread != nil || record == nil {
		return "", nil
	}
	return models[orchestrator].Harness, record
}

// A seatAt is a seat by the name it goes by, its harness, and the pane a line goes into.
type seatAt struct{ name, own, pane string }

func (at seatAt) capture() string {
	shown, err := tmux.Ask(tmux.Own(), "capture-pane", "-p", "-e", "-J", "-t", at.pane)
	if err != nil {
		return ""
	}
	return shown
}

// sight is what that capture shows of the seat, as watch.live_state reads it, writing nothing.
func (at seatAt) sight(shown string) sight {
	found, _ := observed(filepath.Join(config.Home(), "state"), at.name, harness.For(at.own), shown, seconds(time.Now()))
	return found
}

func (at seatAt) composer() (string, bool) { return eyeOf(at.own).rules.ComposerDraft(at.capture()) }

// free is watch._free: a rule or hook says the seat is at its prompt, and no turn runs.
func (at seatAt) free(found sight) bool {
	flight, _ := found.turnInFlight(at.own)
	return found.authority != "" && found.state == "at_prompt" && !flight
}

// takesLine is watch.takes_line: at its own prompt, or stopped on background work, whose composer
// takes a line at once.
func (at seatAt) takesLine() bool {
	shown := at.capture()
	if strings.TrimFunc(shown, unicode.IsSpace) == "" {
		return false
	}
	found := at.sight(shown)
	return at.free(found) || found.onBackground(at.own)
}

// quiet is watch.quiet_prompt, off one capture: it takes a line, asks nothing, and its composer
// reads empty.
func (at seatAt) quiet() bool {
	shown := at.capture()
	if strings.TrimFunc(shown, unicode.IsSpace) == "" {
		return false
	}
	found := at.sight(shown)
	held, drawn := eyeOf(at.own).rules.ComposerDraft(shown)
	return (at.free(found) || found.onBackground(at.own)) && !at.asking(found) && drawn && held == ""
}

func (at seatAt) asking(found sight) bool { return found.authority != "" && found.state == "asking" }

// holds is what the composer holds off one capture, as watch.composer_holds says it of a composer
// read whole: "line" for that line alone, "empty", or "other" for anything else, a question to
// the owner and a composer not found among them.
func (at seatAt) holds(line string) string {
	shown := at.capture()
	if strings.TrimFunc(shown, unicode.IsSpace) == "" || at.asking(at.sight(shown)) {
		return "other"
	}
	switch held, drawn := eyeOf(at.own).rules.ComposerDraft(shown); {
	case !drawn:
		return "other"
	case held == "":
		return "empty"
	case held == screen.Unspaced(line):
		return "line"
	}
	return "other"
}

// sent is watch._pane_sent off one capture: the line left the composer, or a dialog took the screen.
func (at seatAt) sent(line string) bool {
	shown := at.capture()
	if at.asking(at.sight(shown)) {
		return true
	}
	held, drawn := eyeOf(at.own).rules.ComposerDraft(shown)
	return drawn && !strings.Contains(held, screen.Unspaced(line))
}

// enter is one Enter completing the line, watch._send_enter: none while the cursor is off its
// composer.
func (at seatAt) enter(log func(string)) bool {
	if at.offComposer() {
		return false
	}
	if out, err := keys.Type(at.pane, "Enter"); err != nil {
		log("WARN could not type into the " + at.name + " seat: " + tail(out+err.Error(), 200))
		return false
	}
	return true
}

// unasked is a question the seat kept back for its next turn, which Python asks first.
func (at seatAt) unasked() bool {
	file, _ := run.ReadJSON(ownFile("seat", at.name))
	return file != nil && file.Truthy("unasked")
}

// editorKept is whether ak's editor keeps text of this seat or its pinned pane, or tmux cannot
// say (watch._editor_kept).
func (at seatAt) editorKept() bool {
	names, err := tmux.Ask(tmux.Own(), "list-buffers", "-F", "#{buffer_name}")
	if err != nil {
		return true
	}
	if !strings.Contains("\n"+names, "\nak_aside-") {
		return false
	}
	panes, err := tmux.Ask(tmux.Own(), "list-panes", "-s", "-t", "="+at.name+":", "-F", "#{pane_id}")
	if err != nil {
		return true
	}
	buffers := strings.Split(names, "\n")
	for _, pane := range strings.Fields(panes + " " + at.pane) {
		if slices.Contains(buffers, "ak_aside-"+strings.TrimPrefix(pane, "%")) {
			return true
		}
	}
	return false
}

// unread is watch.pane_unread: either terminal of the pane holds input its reader has not read.
func (at seatAt) unread() bool {
	paths, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", at.pane, "#{pane_tty}\t#{"+tmux.InputTTY+"}")
	if err != nil {
		return false
	}
	for _, path := range strings.Split(paths, "\t") {
		if path != "" && ttyUnread(path) {
			return true
		}
	}
	return false
}

// poll asks ready for sentWait, as watch._wait_ready waits for a long conversation to draw a line.
func poll(ready func() bool) bool {
	for range int(sentWait / sentPoll) {
		if ready() {
			return true
		}
		time.Sleep(sentPoll)
	}
	return false
}

// keyed is text as keys type it into a terminal, terminal.keyed: no escape sequence, each control
// character that spaces a space and every other gone.
func keyed(text string) string {
	return strings.Map(func(r rune) rune {
		switch {
		case !unicode.IsControl(r):
			return r
		case unicode.IsSpace(r):
			return ' '
		}
		return -1
	}, escape.ReplaceAllString(text, ""))
}

// created is the seat's tmux birth as orch.find reads it: now where tmux says no number.
func created(said string) int {
	if born, err := strconv.Atoi(said); err == nil {
		return born
	}
	return int(time.Now().Unix())
}

func cutRunes(text string, most int) string {
	if runes := []rune(text); len(runes) > most {
		return string(runes[:most])
	}
	return text
}

func tail(text string, most int) string {
	if len(text) > most {
		return text[len(text)-most:]
	}
	return text
}
