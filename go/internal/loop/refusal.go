package loop

import (
	"path/filepath"
	"strings"

	"agentkit/internal/config"
)

// Refusal is the answer a turn left in out, and what it said in place of one, as Python's
// contract.refused reads a turn that exited non-zero: that answer where it answers nothing, the
// harness's failures, and where it is empty, all the harness said.
func Refusal(out, harness string) (answer, said string) {
	answer = fileTail(filepath.Join(out, "final.md"))
	if !answers(answer) {
		said = answer
	}
	said += "\n" + harnessSaidOf(out, answer, harness, true)
	if strings.TrimFunc(answer, config.Space) == "" {
		said += "\n" + harnessSaidOf(out, answer, harness, false)
	}
	return answer, said
}

// harnessSaidOf is harnessSaid of that harness's turn in out, by its `[stall] terminal`: one kind, a
// string, not a list of words.
func harnessSaidOf(out, text, harness string, failuresOnly bool) string {
	stall, _ := config.Section(harness, "stall")
	terminal, _ := stall["terminal"].(string)
	return harnessSaid(out, text, terminal, failuresOnly)
}
