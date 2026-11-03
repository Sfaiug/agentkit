package cli

import (
	"errors"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/transcript"
)

// The sentences a Stop goes back with, hooks/orchestrator-stop.sh's and agentkit/stop.py's.
const (
	limit      = 2 // blocks in one turn; the third stop stands
	reasonLine = "You stopped with work open and nothing recorded: no question asked through the question " +
		"prompt or ak notify needs, no run or pull request you are waiting on, and an open line " +
		"in your plan. Continue: decide the next step and do it. ak plan checks every open line " +
		"and ticks the proven ones; nothing else ticks a line between runs. A background " +
		"command is no wait: wait on a pull request or run with ak wait <PR url or run id>."
	ask = "Your last message ends in a question, but it went through no question prompt, so the " +
		"owner is not told. Ask it through the question prompt (ak notify needs where there is " +
		"none), or go on without it."
	stuck    = "How should this seat go on? It stopped three times with work open:"
	liveLine = "You reached the live host this turn and your plan has no open line. Write what you " +
		"changed there with ak plan add \"<outcome>\" --check '<command>': a check that " +
		"already passes is written done. If you only read there, end your turn again."
)

// errCards is a turn whose question cards Go cannot read, which only an unanswered one would let
// end where Go sends it back or asks the owner.
var errCards = errors.New("question cards in a conversation only Python reads")

// errParked is a block naming runs parked undecided, whose words (`parked_reason`) only Python
// says yet.
var errParked = errors.New("a parked run's block, which Python words")

// stopHeld is Python's `held` in hooks/orchestrator-stop.sh: the reason this Stop goes back with, ""
// where it stands, each step in Python's order.  The latch the prompt hook writes holds the turn
// and what went back in it.  The error is a read Go cannot make as Python does, found before
// anything is written.
func stopHeld(launched, name string, record map[string]any, harness string, event *run.Object) (string, error) {
	if reason := event.Get("terminationReason"); reason != nil && reason != "" && reason != "NO_TOOL_CALL" {
		return "", nil // a cancelled or failed termination is no turn ending on its words
	}
	turned, _ := run.ReadJSON(latch(launched))
	if turned == nil {
		return "", nil
	}
	turn, ok := turned.Num("turn")
	if !ok {
		return "", nil // no turn written down: nothing here can say what happened in it
	}
	end := transcript.Read(harness, event.Str("transcript_path"))
	said, read := lastSaid(event, end.Said)
	delivery := seat.Reminder(name, said)
	if delivery == "" && (lifecycle.WaitsOn(event) || !read) {
		return "", nil
	}
	asked := end.Asking || notify.NeededSince(name, turn) || seat.Kept(name) || notify.OwnerQuestion(notify.Last(name))
	ends, parked, err := recordedEnding(name, record, asked, turn)
	if err != nil {
		return "", err
	}
	unsure := end.Unread && !asked // a card Go cannot see would have asked
	if ends && delivery == "" {
		return ended(launched, name, turned, asked, unsure, said)
	}
	return counted(launched, name, turned, ends, parked, unsure, delivery, said, record["unnamed"] == true)
}

// ended is a turn that may end: one that reached the live host and wrote nothing of it goes back
// once to write it down, and one ending on a question in prose alone once to ask it.
func ended(launched, name string, turned *run.Object, asked, unsure bool, said string) (string, error) {
	live := !asked && !turned.Truthy("live_back") && plan.LiveUnrecorded(name)
	if !live && (asked || turned.Truthy("asked_back") || !trailsQuestion(said)) {
		return "", nil
	}
	if unsure {
		return "", errCards
	}
	if live {
		return latched(launched, turned, "live_back", true, liveLine), nil
	}
	if refused, err := seat.QuestionRefused(name); refused != "" || err != nil {
		return "", err
	}
	return latched(launched, turned, "asked_back", true, ask), nil
}

// counted is a turn that may not end, or must still say what it asked: it goes back limit times,
// and the next stop stands, the owner asked how the seat goes on where it holds work open.
func counted(launched, name string, turned *run.Object, ends, parked, unsure bool, delivery, said string, unnamed bool) (string, error) {
	blocks, _ := turned.Int("blocks")
	over := blocks+1 > limit
	if unsure && (over && !ends && !parked || !over && delivery == "") {
		return "", errCards
	}
	if blocks++; over {
		if !ends && !parked {
			askOwner(name, said)
		}
		return "", nil
	}
	reason := delivery
	switch {
	case reason != "":
	case parked:
		return "", errParked
	case unnamed:
		reason = seat.NameLine
	default:
		reason = reasonLine
	}
	turned.Set("session", launched)
	return latched(launched, turned, "blocks", blocks, reason), nil
}

// askOwner keeps back for this turn's end the owner's question, the seat's last words after it,
// the end of them where they run long, as Python's `asked_owner` does.
func askOwner(name, said string) {
	words := []rune(strings.Join(strings.FieldsFunc(said, config.Space), " "))
	if len(words) > 200 {
		words = append([]rune("…"), words[len(words)-199:]...)
	}
	if question := stuck + " " + string(words); notify.AsksFirst(question) == nil {
		seat.Keep(name, question)
	}
}

// latched is the reason, once the latch holds key's value; "" where it could not be written.
func latched(launched string, turned *run.Object, key string, value any, reason string) string {
	turned.Set(key, value)
	if relatch(launched, run.Line(turned)) != nil {
		return ""
	}
	return reason
}

// lastSaid is what the model said last, and whether anything was read: the message the Stop
// hands over, in any spelling a harness writes it; else the conversation's, read.
func lastSaid(event *run.Object, read string) (string, bool) {
	for _, key := range []string{"last_assistant_message", "lastAssistantMessage", "finalModelOutput"} {
		if event.Has(key) {
			said, ok := event.Get(key).(string)
			return said, ok
		}
	}
	return read, read != ""
}

// trailsQuestion is whether the message ends in a question mark, past any closing emphasis,
// quote or bracket.
func trailsQuestion(said string) bool {
	said = strings.TrimRight(strings.TrimRightFunc(said, config.Space), "*_`'\"’”»)]}")
	return strings.HasSuffix(said, "?")
}
