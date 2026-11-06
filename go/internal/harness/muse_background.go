package harness

import (
	"slices"

	"agentkit/internal/run"
)

// museBackground is a task's kind in Claude's terms (1.4.12).
var museBackground = map[string]string{"tool.bash": "shell", "workflow.agent.native": "subagent",
	"workflow.run.native": "workflow"}

// museEnded are the events that end a task: its own, a sub-agent's result, and a sub-agent 1.4.13
// names lost once the session its killed process held is resumed, whose send starts a task of its
// own.  The agents a workflow starts are its own work, not the seat's.
var museEnded = []string{"completed", "failed", "cancelled", "rejected", "result_ready", "workflow_child_lifecycle", "recovery_available"}

// museHeld is the work that session's log has running in the background, as Claude's Stop hands
// it over (`background_tasks`), false where there is no log to read (muse.py `background`): a
// terminal, a sub-agent or a workflow it linked `background` as it started, and has not logged the
// end of.
func museHeld(session string) ([]any, bool) {
	log := museLog(session)
	if log == "" {
		return nil, false
	}
	var linked []string
	kinds, gone := map[string]any{}, map[string]bool{}
	for entry := range museEntries(log) {
		payload, _ := entry.Get("payload").(*run.Object)
		event, _ := either(payload, "event", "record").(*run.Object)
		if event == nil {
			continue
		}
		task := event.Get("task_id")
		if ref, ok := either(event, "attempt_ref", "lost_attempt_ref").(*run.Object); ok {
			task = ref.Get("task_id")
		}
		id, ok := task.(string)
		if !ok {
			continue
		}
		switch said, _ := event.Get("kind").(string); {
		case said == "task_stream_linked" && event.Get("execution_mode") == "background":
			linked = append(linked, id)
		case said == "proposed":
			kinds[id] = event.Get("task_kind")
		case slices.Contains(museEnded, said):
			gone[id] = true
		}
	}
	held := []any{}
	for at, id := range linked {
		kind, _ := kinds[id].(string)
		if named, ok := museBackground[kind]; ok && !gone[id] && !slices.Contains(linked[:at], id) {
			held = append(held, run.Fields("id", id, "type", named))
		}
	}
	return held, true
}

// either is the object's first key whose value is true as Python reads it, else its second's, as
// Python's `or` picks one; nil for no object.
func either(object *run.Object, first, second string) any {
	if object == nil {
		return nil
	}
	if object.Truthy(first) {
		return object.Get(first)
	}
	return object.Get(second)
}
