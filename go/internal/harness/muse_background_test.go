package harness

import (
	"slices"
	"testing"

	"agentkit/internal/run"
)

// A session holds the terminals, sub-agents and workflows it linked `background` and has not
// logged the end of: the task's own, a sub-agent's result, or, once resumed, a sub-agent lost with
// its killed process.  A reminder is no work of the seat's, and no log is no answer.
func TestMuseHeldIsWhatItsLogStartedInTheBackgroundAndNeverEnded(t *testing.T) {
	t.Setenv("XDG_DATA_HOME", t.TempDir())
	if _, read := museHeld("acme"); read {
		t.Fatal("a session with no log said what it holds")
	}
	linked := func(task, kind string) []*run.Object {
		return []*run.Object{
			museEvent("kind", "task_stream_linked", "execution_mode", "background", "task_id", task),
			run.Fields("payload", run.Fields("kind", "task", "event", run.Fields("kind", "proposed", "task_id", task, "task_kind", kind)))}
	}
	ended := func(kind, ref, task string) *run.Object {
		return run.Fields("payload", run.Fields("kind", "subagent_control", "record", run.Fields("kind", kind, ref, run.Fields("task_id", task))))
	}
	started := append(append(append(linked("sh", "tool.bash"), linked("agent", "workflow.agent.native")...),
		linked("flow", "workflow.run.native")...), linked("note", "reminder.agent.goal-reminder")...)
	for _, each := range []struct {
		why     string
		entries []*run.Object
		want    []string
	}{
		{"all running", started, []string{"shell", "subagent", "workflow"}},
		{"the terminal completed", append(started[:len(started):len(started)],
			run.Fields("payload", run.Fields("kind", "task", "event", run.Fields("kind", "completed", "task_id", "sh")))), []string{"subagent", "workflow"}},
		{"the sub-agent reported", append(started[:len(started):len(started)], ended("result_ready", "attempt_ref", "agent")), []string{"shell", "workflow"}},
		{"the sub-agent was lost", append(started[:len(started):len(started)], ended("recovery_available", "lost_attempt_ref", "agent")), []string{"shell", "workflow"}},
	} {
		museLogs(t, "acme", each.entries...)
		held, read := museHeld("acme")
		var kinds []string
		for _, task := range held {
			kinds = append(kinds, task.(*run.Object).Str("type"))
		}
		if !read || !slices.Equal(kinds, each.want) {
			t.Errorf("%s: %v, %v", each.why, kinds, read)
		}
	}
}
