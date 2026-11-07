package cli

import (
	"fmt"
	"io"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/handover"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// leftToPython is the exit of the hook under go/hooks named stem, which prints nothing, for what
// Go cannot read as Python does, handed over where it is called.
func leftToPython(stem string) int { return handover.Exit("hook "+stem, handover.Here(1)) }

// questionCard decides the card the seat's harness is about to draw, as the stop hook's PreToolUse
// does: a refused one gets the harness's deny on out; one that goes up has each question it asks
// kept back for the turn's end.
func questionCard(name string, event *run.Object, out io.Writer) int {
	refused, err := seat.QuestionRefused(name)
	if err != nil {
		return leftToPython("orchestrator-stop")
	}
	if refused != "" {
		decision := run.NewObject()
		decision.Set("hookEventName", "PreToolUse")
		decision.Set("permissionDecision", "deny")
		decision.Set("permissionDecisionReason", refused)
		reply := run.NewObject()
		reply.Set("hookSpecificOutput", decision)
		fmt.Fprintln(out, run.Line(reply))
		return 0
	}
	input := event.Dict("tool_input")
	if input == nil {
		return 0
	}
	for _, each := range input.List("questions") {
		asked, _ := each.(*run.Object)
		if asked == nil {
			continue
		}
		text, _ := asked.Get("question").(string)
		if strings.TrimFunc(text, config.Space) != "" && seat.Keep(name, text) != nil {
			return leftToPython("orchestrator-stop")
		}
	}
	return 0
}
