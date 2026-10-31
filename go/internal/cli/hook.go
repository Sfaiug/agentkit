package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/hookfact"
	"agentkit/internal/lifecycle"
	"agentkit/internal/run"
)

// hook carries out what a hook stub under go/hooks hands over: `ak hook <stem>`, the event's
// JSON on stdin.  A hook that fails loudly is a harness that stops, so it reads all its stdin,
// prints nothing and exits 0, whatever it was handed and whatever fails.
func hook(args []string) (code int) {
	defer func() { recover() }()
	payload, _ := io.ReadAll(os.Stdin)
	if len(args) == 1 && args[0] == "seat-state" {
		seatState(payload)
	}
	return 0
}

// subAgent is each key a harness marks a sub-agent's own event with, as hooks/sub-agent.jq
// reads them: its turn is not the seat's.
var subAgent = []string{"agent_id", "agentId", "agent_type", "agentType", "subagentType", "subagent_type"}

// seatState is hooks/seat-state.sh's facts: a prompt's turn, kept under the launch name the
// harness carries, for the stop hook to judge that turn's end against, then the event as what
// the seat is doing, under the name the seat goes by now, unless the fact standing keeps it
// (`lifecycle.Keeps`).  A worker, a harness outside any seat, a sub-agent's turn and a
// SessionStart write nothing.
func seatState(payload []byte) {
	seat := os.Getenv("AGENTKIT_SESSION")
	read, _ := run.Decode(payload)
	event, _ := read.(*run.Object)
	if _, err := config.SessionPath(seat); err != nil || os.Getenv("AK_RUN_ROLE") == "worker" || event == nil {
		return
	}
	name := event.Str("hook_event_name")
	if name == "" || name == "SessionStart" || (name == "UserPromptSubmit" || name == "Stop") && first(event, subAgent...) != nil {
		return
	}
	at := float64(time.Now().UnixNano()) / 1e9
	if name == "UserPromptSubmit" {
		dir := filepath.Join(config.Home(), "state")
		if os.MkdirAll(dir, 0o700) != nil {
			return
		}
		latch := filepath.Join(dir, "stop-"+seat+".json")
		tmp := fmt.Sprintf("%s.tmp.%d", latch, os.Getpid())
		data, _ := json.Marshal(struct {
			Session string  `json:"session"`
			Turn    float64 `json:"turn"`
			Blocks  int     `json:"blocks"`
		}{seat, at, 0})
		if os.WriteFile(tmp, append(data, '\n'), 0o600) != nil {
			os.Remove(tmp)
			return
		}
		if os.Rename(tmp, latch) != nil {
			os.Remove(tmp)
		}
	}
	// `ak orch rename` leaves a pointer at the old name, and the harness carries its launch
	// name for its whole life.
	row := seat
	for hop := 0; hop < config.RenameHops; hop++ {
		path, _ := config.SessionPath(row)
		data, _ := os.ReadFile(path)
		read, _ := run.Decode(data)
		record, _ := read.(*run.Object)
		if record == nil {
			break
		}
		next := record.Str(config.Renamed)
		if _, err := config.SessionPath(next); err != nil {
			break
		}
		row = next
	}
	kind := first(event, "notification_type", "notificationType", "tool_name", "toolName", "trigger")
	text := question(event)
	if text == nil {
		text = first(event, "message", "title")
	}
	fact := hookfact.Fact{Session: seat, Event: name, Kind: printed(kind), Text: printed(text), At: at}
	harness := config.SeatHarness(row)
	// A Stop handing over the work in flight is hooks/orchestrator-stop.sh's, which runs beside
	// this and knows whether the turn ended there; a nudged harness runs no such hook.
	if _, listed := lifecycle.HandedOver(event); name == "Stop" && listed {
		if nudged, err := lifecycle.Nudged(harness); err != nil || !nudged {
			return
		}
		fact = lifecycle.StopFact(seat, event, at)
	}
	hookfact.Record(row, fact, lifecycle.Keeps(harness, fact))
}

// first is the first of the object's keys whose value is neither null nor false, as jq's `//`
// picks one, or nil.
func first(object *run.Object, keys ...string) any {
	for _, key := range keys {
		if value := object.Get(key); value != nil && value != false {
			return value
		}
	}
	return nil
}

// question is the words of a question tool's first question, `(.tool_input.questions[0].question)?`.
func question(event *run.Object) any {
	if input := event.Dict("tool_input"); input != nil {
		if questions := input.List("questions"); len(questions) > 0 {
			if asked, ok := questions[0].(*run.Object); ok {
				return first(asked, "question")
			}
		}
	}
	return nil
}

// printed is a value as `jq -r` prints it into the script's variable: a string as it is,
// anything else as JSON, with its last line breaks cut; "" for none.
func printed(value any) string {
	if value == nil {
		return ""
	}
	text, ok := value.(string)
	if !ok {
		text = run.Encode(value)
	}
	return strings.TrimRight(text, "\n")
}
