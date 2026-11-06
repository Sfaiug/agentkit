package cli

import (
	"fmt"
	"io"

	"agentkit/internal/commandhelp"
	"agentkit/internal/terminal"
)

// askOrchestrator is Python's prompt_orchestrator: every offered model a choice, a number or a
// name, Enter and the end of input taking picked, its suffix after the bracket.  False where Esc
// goes back.
func askOrchestrator(out io.Writer, names []string, picked, suffix string) (string, bool) {
	room := terminal.For(out).Width()
	shown := terminal.PromptLines("Orchestrator ["+picked+"]"+suffix+": ", room)
	for {
		for _, line := range terminal.ChoiceLines(names, room) {
			fmt.Fprintln(out, "  "+terminal.Dim(out, line))
		}
		for _, line := range shown[:len(shown)-1] {
			fmt.Fprintln(out, line)
		}
		answer := terminal.Answer(out, shown[len(shown)-1])
		switch {
		case answer == terminal.Esc:
			return "", false
		case terminal.Sequence(answer):
			continue
		case answer == "":
			return picked, true
		}
		if named := workersNamed(answer, names); len(named) == 1 {
			return named[0], true
		}
		fmt.Fprintln(out, terminal.Dim(out, "not a choice: "+commandhelp.Quote(answer)))
	}
}
