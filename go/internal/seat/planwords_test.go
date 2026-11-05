package seat

import (
	"testing"

	"agentkit/internal/run"
)

func TestAnOpenPlanReadsPythonsStopEpisode(t *testing.T) {
	for name, each := range map[string]struct {
		own, state, word string
		nudged           any
	}{
		"not sent back":       {"claude", "at_prompt", "working", nil},
		"sent back":           {"claude", "at_prompt", "needs you", "The patch is ready."},
		"different words":     {"claude", "at_prompt", "working", "Earlier words."},
		"owner's draft":       {"claude", "draft", "needs you", nil},
		"without a stop hook": {"opencode", "at_prompt", "needs you", []any{run.Number("7"), "The patch is ready."}},
		"another turn":        {"opencode", "at_prompt", "working", []any{run.Number("6"), "The patch is ready."}},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			write(t, stateFile(home, "plan-acme.md"), openLine)
			facts := climbing{name: "acme", own: each.own,
				file:  run.Fields("stop_said", "The patch is ready.", "turn_began", 7, "stop_nudged", each.nudged),
				found: sight{state: each.state, authority: "screen"}}
			said, err := stillOwed(facts)
			if err != nil || said == nil || said.word != each.word {
				t.Fatalf("answer %+v, error %v", said, err)
			}
			reason := "stopped with work open: Ship it"
			if each.word == "working" {
				reason = "going back to its open work: Ship it"
			}
			if said.reason != reason {
				t.Fatal(said.reason)
			}
		})
	}
}

func TestAPlanStopIsReadableAndAnOwnersPromptOutranksIt(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	write(t, stateFile(home, "plan-acme.md"), doneLine+openLine)
	write(t, stateFile(home, "seat-acme.json"), `{"stop_said":"The patch is ready.","stop_nudged":"The patch is ready."}`)
	drawn(t, home, "acme", "The patch is ready.\n"+prompting)
	if lines := explained(t, "acme"); lines[0] != "acme  needs you" {
		t.Fatal(lines)
	}
	hookWrote(t, home, "UserPromptSubmit", "")
	if lines := explained(t, "acme"); lines[0] != "acme  working" {
		t.Fatal(lines)
	}
}
