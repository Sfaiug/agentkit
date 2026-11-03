package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/hookfact"
	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/transcript"
)

// ask is ak's reason for sending back a turn whose question reached nobody but the terminal.
const ask = "Your last message ends in a question, but it went through no question prompt, so the " +
	"owner is not told. Ask it through the question prompt (ak notify needs where there is " +
	"none), or go on without it."

// orchestratorStop judges a seat's Stop as hooks/orchestrator-stop.sh does.  One sent back gets
// its reason on out (`sentBack`); one that stands marks ended the questions the seat kept back
// for it.  Either way a Stop listing the harness's background tasks is written down, under the
// name the seat goes by now: only this hook knows whether the turn ended there.  The PreToolUse
// before a question card is `questionCard`'s.  A worker, a harness outside any seat, a path-like
// name and a sub-agent's event decide nothing.  What Go cannot read leaves it all to Python.
func orchestratorStop(payload []byte, out io.Writer) int {
	// when the Stop was heard, before anything that may wait on a lock: a prompt heard while this
	// judges is the newer fact
	heard, launched := float64(time.Now().UnixNano())/1e9, os.Getenv("AGENTKIT_SESSION")
	read, _ := run.Decode(payload)
	event, ok := read.(*run.Object)
	if !ok {
		event = run.NewObject() // what it was handed says nothing of the turn
	}
	if _, err := config.SessionPath(launched); err != nil || os.Getenv("AK_RUN_ROLE") == "worker" ||
		first(event, subAgent...) != nil {
		return 0
	}
	name, record, err := config.ResolveSession(launched)
	if err != nil {
		name, record = launched, nil
	}
	if event.Str("hook_event_name") == "PreToolUse" {
		return questionCard(name, event, out)
	}
	harness := config.SeatHarness(name)
	back, err := sentBack(launched, name, record, harness, event)
	if err != nil {
		return leftToPython
	}
	if back == "" {
		seat.TurnEnded(name)
	}
	if _, listed := lifecycle.HandedOver(event); listed {
		fact := lifecycle.StopFact(launched, event, heard, back != "")
		hookfact.Record(name, fact, lifecycle.Keeps(harness, fact))
		seat.LookSoon(nil)
	}
	if back != "" {
		reply := run.NewObject()
		reply.Set("decision", "block")
		reply.Set("reason", back)
		fmt.Fprintln(out, run.Line(reply))
	}
	return 0
}

// sentBack is the reason the Stop goes back with, "" where it stands (the stop hook's `held`).
// Go judges a turn whose plan owes nothing: a last message ending in a question that nothing
// asked goes back once, and the turn's latch remembers it.  The Stop stands with no turn
// written down, on work the seat waits on, with no last message read, after a question card
// still unanswered or `ak notify needs`, and where a question would be refused
// (`seat.QuestionRefused`), which holds only the owner; the error is that read Go cannot make.
// What an open plan line, an unnamed seat or a reach of the live host would decide stands too,
// until Go judges those.
func sentBack(launched, name string, record map[string]any, harness string, event *run.Object) (string, error) {
	turned, _ := run.ReadJSON(latch(launched))
	if turned == nil {
		return "", nil
	}
	turn, ok := turned.Num("turn")
	if !ok || turned.Truthy("asked_back") || lifecycle.WaitsOn(event) {
		return "", nil
	}
	end := transcript.Read(harness, event.Str("transcript_path"))
	said := lastSaid(event, end.Said)
	if said == "" || end.Asking || notify.NeededSince(name, turn) || seat.Kept(name) || record["unnamed"] == true {
		return "", nil
	}
	if plan.Owes(name) || !turned.Truthy("live_back") && plan.ReachedLive(name) || !trailsQuestion(said) {
		return "", nil
	}
	if refused, err := seat.QuestionRefused(name); refused != "" || err != nil {
		return "", err
	}
	turned.Set("asked_back", true)
	if relatch(launched, run.Line(turned)) != nil {
		return "", nil
	}
	return ask, nil
}

// lastSaid is what the model said last: the message the Stop hands over, in either spelling a
// harness writes it, "" where it holds no text; else the conversation's, read.
func lastSaid(event *run.Object, read string) string {
	for _, key := range []string{"last_assistant_message", "lastAssistantMessage"} {
		if event.Has(key) {
			said, _ := event.Get(key).(string)
			return said
		}
	}
	return read
}

// trailsQuestion is whether the message ends in a question mark, past any closing emphasis,
// quote or bracket.
func trailsQuestion(said string) bool {
	said = strings.TrimRight(strings.TrimRightFunc(said, config.Space), "*_`'\"’”»)]}")
	return strings.HasSuffix(said, "?")
}

// latch is the turn's latch, which `ak hook seat-state` writes fresh on each prompt under the name
// the seat's harness was launched with: when the turn began, and what the stop hook sent back in
// it.
func latch(launched string) string {
	return filepath.Join(config.Home(), "state", "stop-"+launched+".json")
}

// relatch rewrites the turn's latch whole in one replace, so a reader never sees half of it.
func relatch(launched, record string) error {
	path := latch(launched)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	tmp := fmt.Sprintf("%s.tmp.%d", path, os.Getpid())
	err := os.WriteFile(tmp, []byte(record+"\n"), 0o600)
	if err == nil {
		err = os.Rename(tmp, path)
	}
	if err != nil {
		os.Remove(tmp)
	}
	return err
}
