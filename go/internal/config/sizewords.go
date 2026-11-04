package config

import "fmt"

// The rulebook and task template use the same size wording as Python's config.in_force.
func executorSize(lines int) string {
	return fmt.Sprintf("at most %d added lines with its tests; ak refuses more with `split it`", lines)
}

func orchestratorSize(lines int) string {
	return fmt.Sprintf("you build at most %d added lines; anything bigger you write as a task and an executor builds it while you write the next. ak refuses your own PR above %d lines", lines, lines)
}
