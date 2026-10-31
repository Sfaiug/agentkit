// Package lifecycle is what a fact a seat's hooks heard means, Python's lifecycle with the watch
// helpers beside it: the hook writing facts reads it now, and a seat's word will.  It hides how
// a harness's manifest maps a fact to a state, its `[[hooks.event]]` entries tried in order
// (lifecycle.state); which events carry a mark (watch.marked_events); whether a harness is nudged
// at a turn's end, for want of a blocking stop hook (watch.stop_enforced); the Stop handing over
// background work (lifecycle.stop_fact, waits_on, handed_over); and which fact standing keeps a
// newer one from being written.  No harness is named here: every fact about one is its manifest's.
package lifecycle

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/hookfact"
	"agentkit/internal/run"
)

// live are the states an entry may give a fact (lifecycle.LIVE).
var live = []string{"asking", "working", "at_prompt", "draft"}

// State is the state the harness's manifest gives the fact, and the event as a mark names it,
// `<event>/<kind>` where it has a kind; "" for both where it gives none.
func State(harness string, fact hookfact.Fact) (state, event string, err error) {
	entries, err := config.HookEvents(harness)
	for _, entry := range entries {
		kinds, listed := entry["kinds"].([]any)
		if name, _ := entry["name"].(string); name != fact.Event || listed && !slices.Contains(kinds, any(fact.Kind)) {
			continue
		}
		if state, _ := entry["state"].(string); slices.Contains(live, state) {
			if fact.Kind != "" {
				return state, fact.Event + "/" + fact.Kind, nil
			}
			return state, fact.Event, nil
		}
	}
	return "", "", err
}

// Marked is each event the harness's manifest marks with `mark` (a background wait, an
// interrupt), as State names it; none where it cannot be read.
func Marked(harness, mark string) (marked []string) {
	entries, _ := config.HookEvents(harness)
	for _, entry := range entries {
		name, named := entry["name"].(string)
		if !named || entry[mark] != true {
			continue
		}
		kinds, listed := entry["kinds"].([]any)
		if !listed {
			marked = append(marked, name)
		}
		for _, kind := range kinds {
			if kind, ok := kind.(string); ok {
				marked = append(marked, name+"/"+kind)
			}
		}
	}
	return marked
}

// Nudged is whether the harness's manifest says `[stop] enforce = "nudge"`: with no blocking
// stop hook, its turn's end is typed at it, and hooks/orchestrator-stop.sh never runs there.
func Nudged(harness string) (bool, error) {
	stop, err := config.Section(harness, "stop")
	return stop["enforce"] == "nudge", err
}

// HandedOver is the background work a Stop's payload hands over, `background_tasks`, else
// `backgroundTasks`, and whether it lists any at all: one harness's Stop lists none.
func HandedOver(payload *run.Object) ([]any, bool) {
	found := payload.Get("background_tasks")
	if found == nil {
		found = payload.Get("backgroundTasks")
	}
	tasks, listed := found.([]any)
	return tasks, listed
}

// WaitsOn is whether the payload hands over work the seat started that has not reported back,
// each piece waking the seat again as it settles.  A `monitor`, an artifact's comment watch,
// held a seat working for days; under `background_tasks` neither is a `shell` (a background
// poll the harness kills under memory pressure: a seat waits through `ak wait`), nor a
// `terminal` or a plugin's `agent`, whose end starts no turn.
func WaitsOn(payload *run.Object) bool {
	idle := []string{"monitor"}
	if payload.Get("background_tasks") != nil {
		idle = append(idle, "shell", "terminal", "agent")
	}
	tasks, _ := HandedOver(payload)
	for _, task := range tasks {
		if task, ok := task.(*run.Object); ok && !slices.Contains(idle, task.Str("type")) {
			return true
		}
	}
	return false
}

// StopFact is the Stop of a payload handing over background work, heard at, as its one writer
// puts it down: kind `held` where it was sent back, `background` while it waits on work, and
// `holds` the type of each task still in flight, shells and monitors too.
func StopFact(session string, payload *run.Object, at float64, held bool) hookfact.Fact {
	fact := hookfact.Fact{Session: session, Event: "Stop", At: at}
	if held {
		fact.Kind = "held"
	} else if WaitsOn(payload) {
		fact.Kind = "background"
	}
	tasks, _ := HandedOver(payload)
	for _, task := range tasks {
		if task, ok := task.(*run.Object); ok {
			kind := task.Str("type")
			if kind == "" {
				kind = "task"
			}
			fact.Holds = append(fact.Holds, kind)
		}
	}
	return fact
}

// Keeps is the rule hookfact.Record judges the fact by, against the one standing, on the seat's
// harness ("" where nothing names it).  A harness may say its prompt is idle a minute after a
// turn ends, background work in flight or not: a seat waiting on work it started is not idle,
// and the Stop that said so stands until that work's notification begins a turn.  An event
// other than a prompt or a Stop that the manifest gives no state, or the state standing, adds
// nothing -- a permission notice six seconds after the PermissionRequest that wrote its question
// down -- unless the manifest marks it `interrupt`: the owner stopped a turn a harness with no
// prompt hook began under an earlier Stop's at_prompt, which that Stop does not say.  Where
// nothing can say, no harness or its manifest unread, the event is written.
func Keeps(harness string, fact hookfact.Fact) func(standing hookfact.Fact) bool {
	passive, state := false, ""
	if harness != "" && fact.Event != "UserPromptSubmit" && fact.Event != "Stop" {
		var event string
		var err error
		state, event, err = State(harness, fact)
		passive = err == nil && !slices.Contains(Marked(harness, "interrupt"), event)
	}
	return func(standing hookfact.Fact) bool {
		if fact.Event == "Notification" && fact.Kind == "idle_prompt" && standing.Event == "Stop" &&
			standing.Kind == "background" {
			return true
		}
		if !passive {
			return false
		}
		held, _, _ := State(harness, standing)
		return state == "" || state == held
	}
}
