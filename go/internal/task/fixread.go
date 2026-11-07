package task

import "strings"

// IsFix recognizes both current fix instructions and tasks saved before the tip check,
// as Python's Loop.fix_run does.
func IsFix(body string) bool {
	const old = "Your checkout starts on the target branch's tip, fetched when this run " +
		"started: run the command below there first. If it " +
		"passes there now, run `ak hand-in not-needed \"<why>\"`, with no edits or PR. " +
		"Otherwise fix the root cause so it passes, and show it failing before the " +
		"fix and passing afterwards in your summary. If only the owner can decide, " +
		"run `ak hand-in blocked \"<question>\"`."
	return strings.Contains(body, FixTheCommand) || strings.Contains(body, old)
}
