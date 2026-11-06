package config

import (
	"fmt"
	"regexp"
)

// ExecutorsOff is what executors off means, in ak's words of a task's size and in a task launch's
// refusal (Python's EXECUTORS_OFF).
const ExecutorsOff = "Executors are off; the orchestrator builds every change itself."

// sizeLine is a line of ak's words saying a task's size, as a list item or not.
var sizeLine = regexp.MustCompile(`(?m)^([ \t]*(?:- )?)[^\n]*\$executor_size[^\n]*`)

// sizes is ak's words with each line saying a task's size said whole as executors off where they
// are, and what the size placeholders say, as Python's config.in_force says them.
func sizes(text string, executor, orchestrator Lines) (string, map[string]string) {
	words := map[string]string{"executor_size": "no limit on added lines, tests included", "orchestrator_size": "you build with no line limit"}
	if most, limited := executor.Most(); limited {
		words["executor_size"] = fmt.Sprintf("at most %d added lines with its tests; ak refuses more with `split it`", most)
	}
	most, limited := orchestrator.Most()
	if limited {
		words["orchestrator_size"] = fmt.Sprintf("you build at most %d added lines; anything bigger you write as a task and an executor builds it while you write the next. ak refuses your own PR above %d lines", most, most)
	}
	if executor == AtMost(0) {
		text = sizeLine.ReplaceAllString(text, "${1}"+ExecutorsOff)
		if limited {
			words["orchestrator_size"] = fmt.Sprintf("you build at most %d added lines per PR; split larger changes", most)
		}
	}
	return text, words
}
