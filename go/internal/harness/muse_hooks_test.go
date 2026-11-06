package harness

import (
	"testing"

	"agentkit/internal/run"
)

func TestMuseBatchIsNamedForItsFirstTool(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("AGENTKIT_SESSION", "acme")
	t.Setenv("AK_RUN_ROLE", "")
	for _, each := range []struct{ payload, want string }{
		{`{"tool_calls":[{"tool_name":"request_user_input"},{"tool_name":"shell"}]}`, "request_user_input"},
		{`{"tool_calls":[{"tool_name":"submit_reminder_decision"},{"tool_name":"request_user_input"}]}`, "submit_reminder_decision"},
		{`{"tool_name":"shell","tool_calls":[{"tool_name":"request_user_input"}]}`, "shell"},
		{`{"tool_calls":[]}`, ""},
		{`{"tool_calls":[null]}`, ""},
	} {
		read, _ := run.Decode([]byte(each.payload))
		event := museHookEvent(read.(*run.Object))
		if event == nil || event.Str("tool_name") != each.want {
			t.Fatalf("%s became %v, want %q", each.payload, event, each.want)
		}
	}
}

func TestMuseQuestionUsesTheLastRunningDialog(t *testing.T) {
	heading := "◆ Request user input Colour — running (4s)\n"
	for _, each := range []struct{ pane, want string }{
		{heading + "\n  Which colour?  \n  1. Red\n", "Which colour?"},
		{heading + "Old question\n" + heading + "\n New question\n", "New question"},
		{heading + "Old question\n" + heading + "\n", ""},
		{"Which colour?\n  1. Red\n", ""},
	} {
		if got := museQuestion(each.pane); got != each.want {
			t.Fatalf("%q gave %q, want %q", each.pane, got, each.want)
		}
	}
}

func TestMuseHooksOutsideASeatAndSessionStartsSupplyNoFact(t *testing.T) {
	event := run.NewObject()
	for _, each := range []struct{ seat, role, event string }{
		{"", "", "Notification"}, {"../outside", "", "Stop"},
		{"acme", "worker", "Stop"}, {"acme", "", "SessionStart"},
	} {
		t.Setenv("AGENTKIT_SESSION", each.seat)
		t.Setenv("AK_RUN_ROLE", each.role)
		event.Set("hook_event_name", each.event)
		if got := museHookEvent(event); got != nil {
			t.Fatalf("%+v supplied a fact: %v", each, got)
		}
	}
}
