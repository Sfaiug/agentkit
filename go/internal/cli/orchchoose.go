package cli

import (
	"fmt"
	"io"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

func askOrchestrator(out io.Writer) (name, reason string, ok bool, err error) {
	names, err := config.Offered()
	if err != nil {
		return "", "", false, err
	}
	defaultName, err := config.DefaultOrchestrator()
	if err != nil {
		return "", "", false, err
	}
	for {
		for _, line := range terminal.ChoiceLines(names, terminal.For(out).Width()) {
			fmt.Fprintln(out, "  "+terminal.Dim(out, line))
		}
		answer := terminal.Answer(out, "Orchestrator ["+defaultName+"]: ")
		switch {
		case answer == terminal.Esc:
			return "", "", false, nil
		case terminal.Sequence(answer):
			continue
		case answer == "":
			return defaultName, "default", true, nil
		}
		if picked := workersNamed(answer, names); len(picked) == 1 {
			reason = "default"
			if picked[0] != defaultName {
				reason = "selected"
			}
			return picked[0], reason, true, nil
		}
		fmt.Fprintln(out, terminal.Dim(out, "not a choice: "+commandhelp.Quote(answer)))
	}
}
