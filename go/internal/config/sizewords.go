package config

import "fmt"

// The rulebook and task template use the same size wording as Python's config.in_force.
func executorSize(lines Lines) string {
	most, limited := lines.Most()
	if !limited {
		return "no limit on added lines, tests included"
	}
	return fmt.Sprintf("at most %d added lines with its tests; ak refuses more with `split it`", most)
}

func orchestratorSize(lines Lines) string {
	most, limited := lines.Most()
	if !limited {
		return "you build with no line limit"
	}
	return fmt.Sprintf("you build at most %d added lines; anything bigger you write as a task and an executor builds it while you write the next. ak refuses your own PR above %d lines", most, most)
}
