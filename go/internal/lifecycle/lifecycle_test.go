package lifecycle

import (
	"slices"
	"testing"

	"agentkit/internal/hookfact"
	"agentkit/internal/run"
)

func TestTheManifestSaysWhichFactAddsNothingToTheOneStanding(t *testing.T) {
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	asked := hookfact.Fact{Event: "PermissionRequest", Kind: "Bash", At: 1}
	waiting := hookfact.Fact{Event: "Stop", Kind: "background", At: 1}
	prompt := hookfact.Fact{Event: "UserPromptSubmit", At: 1}
	for _, each := range []struct {
		harness        string
		fact, standing hookfact.Fact
		kept           bool
	}{
		{"claude", hookfact.Fact{Event: "Notification", Kind: "permission_prompt"}, asked, true},
		{"claude", hookfact.Fact{Event: "PreCompact", Kind: "auto"}, asked, true},
		{"claude", hookfact.Fact{Event: "PreCompact", Kind: "manual"}, asked, false},
		{"", hookfact.Fact{Event: "Notification", Kind: "permission_prompt"}, asked, false},
		{"", hookfact.Fact{Event: "Notification", Kind: "idle_prompt"}, waiting, true},
		{"claude", hookfact.Fact{Event: "Stop"}, hookfact.Fact{Event: "Stop", At: 1}, false},
		// stateless, but the owner stopped the turn
		{"opencode", hookfact.Fact{Event: "Interrupt"}, hookfact.Fact{Event: "Stop", At: 1}, false},
		{"opencode", hookfact.Fact{Event: "Notification"}, prompt, true},
	} {
		if kept := Keeps(each.harness, each.fact)(each.standing); kept != each.kept {
			t.Errorf("on %q %+v over %+v kept %v, want %v", each.harness, each.fact, each.standing, kept, each.kept)
		}
	}
}

func TestAStopHoldsEachTaskItHandsOverAndWaitsOnlyOnWork(t *testing.T) {
	for _, each := range []struct {
		payload, kind string
		holds         []string
	}{
		{`{"background_tasks": [{"type": "subagent"}, {"type": "shell"}, {}]}`, "background", []string{"subagent", "shell", "task"}},
		{`{"background_tasks": [{"type": "shell"}, {"type": "monitor"}]}`, "", []string{"shell", "monitor"}},
		{`{"backgroundTasks": [{"type": "shell"}]}`, "background", []string{"shell"}},
		{`{"background_tasks": []}`, "", nil},
	} {
		read, _ := run.Decode([]byte(each.payload))
		fact := StopFact("acme", read.(*run.Object), 5)
		if fact.Event != "Stop" || fact.Kind != each.kind || !slices.Equal(fact.Holds, each.holds) || fact.At != 5 {
			t.Errorf("%s is %+v, want kind %q holding %v", each.payload, fact, each.kind, each.holds)
		}
	}
}
